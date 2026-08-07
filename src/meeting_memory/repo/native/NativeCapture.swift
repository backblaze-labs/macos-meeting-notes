import AVFoundation
import CoreAudio
import CoreMedia
import Foundation
import ScreenCaptureKit

enum CaptureMode: String {
    case fullMeeting = "full-meeting"
    case silentSystemOnly = "silent-system-only"
}

enum CaptureError: LocalizedError {
    case noDisplay
    case noMicrophone
    case invalidAudioBuffer
    case unsupportedSystem
    case coreAudio(String, OSStatus)
    case message(String)

    var errorDescription: String? {
        switch self {
        case .noDisplay:
            return "No display is available for system-audio capture."
        case .noMicrophone:
            return "No default microphone is available."
        case .invalidAudioBuffer:
            return "macOS returned an invalid audio buffer."
        case .unsupportedSystem:
            return "Native meeting capture requires macOS 15 or newer."
        case let .coreAudio(action, status):
            return "Core Audio could not \(action) (OSStatus \(status))."
        case let .message(message):
            return message
        }
    }
}

final class WAVWriter {
    private let handle: FileHandle
    private var dataBytes: UInt32 = 0
    private let sampleRate: UInt32

    init(url: URL, sampleRate: UInt32 = 16_000) throws {
        self.sampleRate = sampleRate
        FileManager.default.createFile(atPath: url.path, contents: nil)
        handle = try FileHandle(forWritingTo: url)
        try writeHeader()
    }

    deinit {
        try? close()
    }

    func append(_ samples: [Float]) throws {
        guard !samples.isEmpty else { return }
        let pcm = samples.map { sample -> Int16 in
            let clipped = max(-1.0, min(1.0, sample))
            return Int16(clipped * Float(Int16.max))
        }
        try pcm.withUnsafeBytes { rawBuffer in
            try handle.write(contentsOf: rawBuffer)
        }
        dataBytes += UInt32(pcm.count * MemoryLayout<Int16>.size)
        try patchSizes()
    }

    func close() throws {
        try patchSizes()
        try handle.close()
    }

    private func writeHeader() throws {
        var header = Data()
        header.append("RIFF".data(using: .ascii)!)
        header.appendLittleEndian(UInt32(36))
        header.append("WAVEfmt ".data(using: .ascii)!)
        header.appendLittleEndian(UInt32(16))
        header.appendLittleEndian(UInt16(1))
        header.appendLittleEndian(UInt16(1))
        header.appendLittleEndian(sampleRate)
        header.appendLittleEndian(sampleRate * 2)
        header.appendLittleEndian(UInt16(2))
        header.appendLittleEndian(UInt16(16))
        header.append("data".data(using: .ascii)!)
        header.appendLittleEndian(UInt32(0))
        try handle.write(contentsOf: header)
    }

    private func patchSizes() throws {
        try handle.seek(toOffset: 4)
        var riffSize = UInt32(36) + dataBytes
        try Swift.withUnsafeBytes(of: &riffSize) { try handle.write(contentsOf: $0) }
        try handle.seek(toOffset: 40)
        var payloadSize = dataBytes
        try Swift.withUnsafeBytes(of: &payloadSize) { try handle.write(contentsOf: $0) }
        try handle.seekToEnd()
    }
}

private extension Data {
    mutating func appendLittleEndian<T: FixedWidthInteger>(_ value: T) {
        var littleEndian = value.littleEndian
        Swift.withUnsafeBytes(of: &littleEndian) { append(contentsOf: $0) }
    }
}

final class PCMConverter {
    private let targetFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: 16_000,
        channels: 1,
        interleaved: false
    )!
    private var converter: AVAudioConverter?
    private var sourceFormat: AVAudioFormat?

    func samples(from sampleBuffer: CMSampleBuffer) throws -> [Float] {
        guard let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer) else {
            throw CaptureError.invalidAudioBuffer
        }
        let format = AVAudioFormat(cmAudioFormatDescription: formatDescription)

        let frameCount = AVAudioFrameCount(CMSampleBufferGetNumSamples(sampleBuffer))
        guard let input = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
            throw CaptureError.invalidAudioBuffer
        }
        input.frameLength = frameCount
        let copyStatus = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sampleBuffer,
            at: 0,
            frameCount: Int32(frameCount),
            into: input.mutableAudioBufferList
        )
        guard copyStatus == noErr else {
            throw CaptureError.coreAudio("copy captured PCM", copyStatus)
        }

        return try samples(from: input)
    }

    func samples(from input: AVAudioPCMBuffer) throws -> [Float] {
        let format = input.format
        let frameCount = input.frameLength

        if sourceFormat != format {
            sourceFormat = format
            converter = AVAudioConverter(from: format, to: targetFormat)
            converter?.downmix = true
            converter?.sampleRateConverterQuality = AVAudioQuality.max.rawValue
        }
        guard let converter else {
            throw CaptureError.message("The captured audio format cannot be converted.")
        }

        let ratio = targetFormat.sampleRate / format.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(frameCount) * ratio) + 64)
        guard let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else {
            throw CaptureError.invalidAudioBuffer
        }

        var suppliedInput = false
        var conversionError: NSError?
        let status = converter.convert(to: output, error: &conversionError) { _, inputStatus in
            if suppliedInput {
                inputStatus.pointee = .noDataNow
                return nil
            }
            suppliedInput = true
            inputStatus.pointee = .haveData
            return input
        }
        guard status != .error else {
            throw conversionError ?? CaptureError.message("Audio conversion failed.")
        }
        guard let channel = output.floatChannelData?[0] else { return [] }
        return Array(UnsafeBufferPointer(start: channel, count: Int(output.frameLength)))
    }
}

final class TimelineMixer {
    enum Source: Hashable {
        case system
        case microphone
    }

    private let writer: WAVWriter
    private let enabledSources: Set<Source>
    private var anchorSeconds: Double?
    private var pending: [Float] = []
    private var pendingBaseFrame: Int64 = 0
    private var highWater: [Source: Int64] = [:]
    private var capturedFrames: [Source: Int64] = [:]
    private var capturedPeaks: [Source: Float] = [:]

    init(writer: WAVWriter, enabledSources: Set<Source>) {
        self.writer = writer
        self.enabledSources = enabledSources
    }

    func add(_ samples: [Float], source: Source, presentationSeconds: Double) throws {
        guard enabledSources.contains(source), !samples.isEmpty else { return }
        capturedFrames[source, default: 0] += Int64(samples.count)
        let peak = samples.reduce(Float.zero) { max($0, abs($1)) }
        capturedPeaks[source] = max(capturedPeaks[source] ?? 0, peak)
        if anchorSeconds == nil {
            anchorSeconds = presentationSeconds
        }
        guard let anchorSeconds else { return }

        var startFrame = Int64(((presentationSeconds - anchorSeconds) * 16_000).rounded())
        var values = samples
        if startFrame < pendingBaseFrame {
            let trim = min(values.count, Int(pendingBaseFrame - startFrame))
            values.removeFirst(trim)
            startFrame += Int64(trim)
        }
        guard !values.isEmpty else { return }

        let endFrame = startFrame + Int64(values.count)
        let required = Int(max(0, endFrame - pendingBaseFrame))
        if pending.count < required {
            pending.append(contentsOf: repeatElement(0, count: required - pending.count))
        }
        let offset = Int(startFrame - pendingBaseFrame)
        let gain: Float = enabledSources.count > 1 ? 0.75 : 1.0
        for index in values.indices {
            pending[offset + index] += values[index] * gain
        }
        highWater[source] = max(highWater[source] ?? 0, endFrame)
        try flushCompletedFrames()
    }

    func finish() throws {
        if let finalFrame = highWater.values.max() {
            try flush(through: finalFrame)
        }
        try writer.close()
    }

    func metrics() -> [String: Any] {
        var values: [String: Any] = [:]
        for source in enabledSources {
            let name = source == .system ? "system" : "microphone"
            values[name] = [
                "frames": capturedFrames[source] ?? 0,
                "peak": capturedPeaks[source] ?? 0,
            ]
        }
        return values
    }

    private func flushCompletedFrames() throws {
        guard enabledSources.allSatisfy({ highWater[$0] != nil }) else { return }
        let completedFrame = enabledSources.compactMap { highWater[$0] }.min() ?? pendingBaseFrame
        try flush(through: completedFrame)
    }

    private func flush(through frame: Int64) throws {
        let count = min(pending.count, Int(max(0, frame - pendingBaseFrame)))
        guard count > 0 else { return }
        try writer.append(Array(pending.prefix(count)))
        pending.removeFirst(count)
        pendingBaseFrame += Int64(count)
    }
}

@available(macOS 15.0, *)
final class ScreenCaptureRecorder: NSObject, SCStreamOutput, SCStreamDelegate {
    private let mixer: TimelineMixer
    private let includeMicrophone: Bool
    private let captureQueue = DispatchQueue(label: "com.meeting-memory.native-capture")
    private let systemConverter = PCMConverter()
    private let microphoneConverter = PCMConverter()
    private var stream: SCStream?
    private var continuation: CheckedContinuation<Void, Error>?
    private var stopped = false

    init(mixer: TimelineMixer, includeMicrophone: Bool) {
        self.mixer = mixer
        self.includeMicrophone = includeMicrophone
    }

    func start() async throws -> String? {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false,
            onScreenWindowsOnly: false
        )
        guard let display = content.displays.first else { throw CaptureError.noDisplay }
        let microphone = includeMicrophone ? AVCaptureDevice.default(for: .audio) : nil
        if includeMicrophone && microphone == nil { throw CaptureError.noMicrophone }

        let ownBundleID = Bundle.main.bundleIdentifier
        let excludedApps = content.applications.filter { $0.bundleIdentifier == ownBundleID }
        let filter = SCContentFilter(
            display: display,
            excludingApplications: excludedApps,
            exceptingWindows: []
        )
        let configuration = SCStreamConfiguration()
        configuration.width = 2
        configuration.height = 2
        configuration.capturesAudio = true
        configuration.excludesCurrentProcessAudio = true
        configuration.sampleRate = 48_000
        configuration.channelCount = 2
        configuration.captureMicrophone = includeMicrophone
        configuration.microphoneCaptureDeviceID = microphone?.uniqueID

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: captureQueue)
        if includeMicrophone {
            try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: captureQueue)
        }
        self.stream = stream
        try await stream.startCapture()
        return microphone?.localizedName
    }

    func stop() async throws {
        guard !stopped else { return }
        stopped = true
        try await stream?.stopCapture()
        try captureQueue.sync { try mixer.finish() }
        stream = nil
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        guard sampleBuffer.isValid else { return }
        do {
            let seconds = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
            switch outputType {
            case .audio:
                try mixer.add(
                    systemConverter.samples(from: sampleBuffer),
                    source: .system,
                    presentationSeconds: seconds
                )
            case .microphone:
                try mixer.add(
                    microphoneConverter.samples(from: sampleBuffer),
                    source: .microphone,
                    presentationSeconds: seconds
                )
            default:
                break
            }
        } catch {
            emitJSON(["event": "error", "message": error.localizedDescription])
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emitJSON(["event": "error", "message": error.localizedDescription])
    }
}

final class SilentSystemRecorder {
    private let mixer: TimelineMixer
    private let converter = PCMConverter()
    private let queue = DispatchQueue(label: "com.meeting-memory.silent-capture")
    private var tapID: AudioObjectID = kAudioObjectUnknown
    private var aggregateID: AudioObjectID = kAudioObjectUnknown
    private var ioProcID: AudioDeviceIOProcID?
    private var format = AudioStreamBasicDescription()
    private var sampleTimeAnchor: Double?

    init(mixer: TimelineMixer) {
        self.mixer = mixer
    }

    func start() throws {
        guard #available(macOS 14.2, *) else { throw CaptureError.unsupportedSystem }
        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        description.name = "Meeting Memory Silent Capture"
        description.isPrivate = true
        description.muteBehavior = .muted
        try check(
            AudioHardwareCreateProcessTap(description, &tapID),
            "create the silent system-audio tap"
        )

        try readTapFormat()
        let tapEntry: [String: Any] = [
            kAudioSubTapUIDKey: description.uuid.uuidString,
            kAudioSubTapDriftCompensationKey: true,
        ]
        let aggregateDescription: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Meeting Memory Silent Capture",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceSubDeviceListKey: [],
            kAudioAggregateDeviceTapListKey: [tapEntry],
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceIsPrivateKey: true,
        ]
        try check(
            AudioHardwareCreateAggregateDevice(
                aggregateDescription as CFDictionary,
                &aggregateID
            ),
            "create the silent capture device"
        )

        var procID: AudioDeviceIOProcID?
        try check(
            AudioDeviceCreateIOProcIDWithBlock(
                &procID,
                aggregateID,
                queue
            ) { [weak self] _, inputData, inputTime, _, _ in
                self?.receive(inputData: inputData, inputTime: inputTime)
            },
            "start reading the silent system-audio tap"
        )
        ioProcID = procID
        if let procID {
            try check(AudioDeviceStart(aggregateID, procID), "start silent system capture")
        }
    }

    func stop() throws {
        if aggregateID != kAudioObjectUnknown, let ioProcID {
            _ = AudioDeviceStop(aggregateID, ioProcID)
            _ = AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
        }
        if aggregateID != kAudioObjectUnknown {
            _ = AudioHardwareDestroyAggregateDevice(aggregateID)
        }
        if tapID != kAudioObjectUnknown {
            _ = AudioHardwareDestroyProcessTap(tapID)
        }
        ioProcID = nil
        aggregateID = kAudioObjectUnknown
        tapID = kAudioObjectUnknown
        try mixer.finish()
    }

    private func receive(
        inputData: UnsafePointer<AudioBufferList>,
        inputTime: UnsafePointer<AudioTimeStamp>
    ) {
        do {
            guard
                let audioFormat = AVAudioFormat(streamDescription: &format),
                let buffer = AVAudioPCMBuffer(
                    pcmFormat: audioFormat,
                    bufferListNoCopy: inputData,
                    deallocator: nil
                )
            else {
                throw CaptureError.invalidAudioBuffer
            }
            let frames = inputData.pointee.mBuffers.mDataByteSize / max(1, format.mBytesPerFrame)
            buffer.frameLength = AVAudioFrameCount(frames)
            let sampleTime = inputTime.pointee.mSampleTime
            if sampleTimeAnchor == nil { sampleTimeAnchor = sampleTime }
            let seconds = (sampleTime - (sampleTimeAnchor ?? sampleTime)) / format.mSampleRate
            try mixer.add(
                converter.samples(from: buffer),
                source: .system,
                presentationSeconds: seconds
            )
        } catch {
            emitJSON(["event": "error", "message": error.localizedDescription])
        }
    }

    private func readTapFormat() throws {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyFormat,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        try check(
            AudioObjectGetPropertyData(tapID, &address, 0, nil, &size, &format),
            "read the system-audio tap format"
        )
    }

    private func check(_ status: OSStatus, _ action: String) throws {
        guard status == noErr else { throw CaptureError.coreAudio(action, status) }
    }
}

func emitJSON(_ payload: [String: Any]) {
    guard
        JSONSerialization.isValidJSONObject(payload),
        let data = try? JSONSerialization.data(withJSONObject: payload),
        let line = String(data: data, encoding: .utf8)
    else { return }
    FileHandle.standardOutput.write(Data((line + "\n").utf8))
}

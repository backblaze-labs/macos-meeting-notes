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
    private var arrivalAnchorSeconds: Double?
    private var sourceAnchors: [Source: (presentation: Double, arrival: Double)] = [:]
    private var pending: [Float] = []
    private var pendingBaseFrame: Int64 = 0
    private var highWater: [Source: Int64] = [:]
    private var capturedCallbacks: [Source: Int64] = [:]
    private var capturedFrames: [Source: Int64] = [:]
    private var capturedPeaks: [Source: Float] = [:]
    private var discardedFrames: [Source: Int64] = [:]
    private var firstArrivals: [Source: Double] = [:]
    private var lastArrivals: [Source: Double] = [:]

    init(writer: WAVWriter, enabledSources: Set<Source>) {
        self.writer = writer
        self.enabledSources = enabledSources
    }

    func add(
        _ samples: [Float],
        source: Source,
        presentationSeconds: Double,
        arrivalSeconds: Double
    ) throws {
        guard enabledSources.contains(source), !samples.isEmpty else { return }
        guard presentationSeconds.isFinite, arrivalSeconds.isFinite else {
            throw CaptureError.invalidAudioBuffer
        }
        capturedCallbacks[source, default: 0] += 1
        capturedFrames[source, default: 0] += Int64(samples.count)
        let peak = samples.reduce(Float.zero) { max($0, abs($1)) }
        capturedPeaks[source] = max(capturedPeaks[source] ?? 0, peak)
        firstArrivals[source] = firstArrivals[source] ?? arrivalSeconds
        lastArrivals[source] = arrivalSeconds
        if arrivalAnchorSeconds == nil {
            arrivalAnchorSeconds = arrivalSeconds
        }
        sourceAnchors[source] = sourceAnchors[source] ?? (presentationSeconds, arrivalSeconds)
        guard let arrivalAnchorSeconds, let sourceAnchor = sourceAnchors[source] else { return }

        let relativeSeconds = sourceAnchor.arrival - arrivalAnchorSeconds
            + presentationSeconds - sourceAnchor.presentation
        let relativeFrame = (relativeSeconds * 16_000).rounded()
        guard
            relativeFrame.isFinite,
            relativeFrame >= Double(Int64.min),
            relativeFrame <= Double(Int64.max)
        else {
            throw CaptureError.invalidAudioBuffer
        }
        var startFrame = Int64(relativeFrame)
        var values = samples
        if startFrame < pendingBaseFrame {
            let trim = min(values.count, Int(pendingBaseFrame - startFrame))
            discardedFrames[source, default: 0] += Int64(trim)
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

    func metrics(startedAt: Double, now: Double) -> [String: Any] {
        var values: [String: Any] = [:]
        for source in enabledSources {
            let name = source == .system ? "system" : "microphone"
            let first = firstArrivals[source].map { max(0, $0 - startedAt) }
            let last = lastArrivals[source].map { max(0, min(now, $0) - startedAt) }
            values[name] = [
                "callbacks": capturedCallbacks[source] ?? 0,
                "frames": capturedFrames[source] ?? 0,
                "peak": capturedPeaks[source] ?? 0,
                "discarded_frames": discardedFrames[source] ?? 0,
                "first_callback_seconds": first.map { $0 as Any } ?? NSNull(),
                "last_callback_seconds": last.map { $0 as Any } ?? NSNull(),
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

import AVFoundation
import CoreAudio
import Foundation

final class SilentSystemRecorder {
    private let mixer: TimelineMixer
    private let failureHandler: (Error) -> Void
    private let converter = PCMConverter()
    private let queue = DispatchQueue(label: "com.meeting-memory.silent-capture")
    private var tapID: AudioObjectID = kAudioObjectUnknown
    private var aggregateID: AudioObjectID = kAudioObjectUnknown
    private var ioProcID: AudioDeviceIOProcID?
    private var format = AudioStreamBasicDescription()
    private var sampleTimeAnchor: Double?

    init(mixer: TimelineMixer, failureHandler: @escaping (Error) -> Void) {
        self.mixer = mixer
        self.failureHandler = failureHandler
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
            failureHandler(error)
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

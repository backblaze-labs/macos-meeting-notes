import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

@available(macOS 15.0, *)
final class ScreenCaptureRecorder: NSObject, SCStreamOutput, SCStreamDelegate {
    private let mixer: TimelineMixer
    private let includeMicrophone: Bool
    private let failureHandler: (Error) -> Void
    private let captureQueue = DispatchQueue(label: "com.meeting-memory.native-capture")
    private let systemConverter = PCMConverter()
    private let microphoneConverter = PCMConverter()
    private var stream: SCStream?
    private var stopped = false

    init(
        mixer: TimelineMixer,
        includeMicrophone: Bool,
        failureHandler: @escaping (Error) -> Void
    ) {
        self.mixer = mixer
        self.includeMicrophone = includeMicrophone
        self.failureHandler = failureHandler
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
            let arrivalSeconds = ProcessInfo.processInfo.systemUptime
            let seconds = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
            switch outputType {
            case .audio:
                try mixer.add(
                    systemConverter.samples(from: sampleBuffer),
                    source: .system,
                    presentationSeconds: seconds,
                    arrivalSeconds: arrivalSeconds
                )
            case .microphone:
                try mixer.add(
                    microphoneConverter.samples(from: sampleBuffer),
                    source: .microphone,
                    presentationSeconds: seconds,
                    arrivalSeconds: arrivalSeconds
                )
            default:
                break
            }
        } catch {
            failureHandler(error)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        guard !stopped else { return }
        failureHandler(error)
    }
}

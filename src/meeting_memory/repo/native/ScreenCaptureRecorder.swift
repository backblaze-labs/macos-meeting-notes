import AVFoundation
import CoreAudio
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
    private let routeQueue = DispatchQueue(label: "com.meeting-memory.microphone-route")
    private var stream: SCStream?
    private var routeMonitor: DefaultInputMonitor?
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
        let configuration = streamConfiguration()

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: captureQueue)
        if includeMicrophone {
            try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: captureQueue)
        }
        self.stream = stream
        try await stream.startCapture()
        if includeMicrophone {
            let monitor = DefaultInputMonitor(queue: routeQueue)
            try monitor.start { [weak self] in self?.refreshMicrophoneRoute() }
            routeMonitor = monitor
        }
        return microphone?.localizedName
    }

    func stop() async throws {
        guard !stopped else { return }
        stopped = true
        routeMonitor?.stop()
        routeMonitor = nil
        try await stream?.stopCapture()
        try captureQueue.sync { try mixer.finish() }
        stream = nil
    }

    func metrics(startedAt: Double, now: Double) -> [String: Any] {
        captureQueue.sync { mixer.metrics(startedAt: startedAt, now: now) }
    }

    private func streamConfiguration() -> SCStreamConfiguration {
        let configuration = SCStreamConfiguration()
        configuration.width = 2
        configuration.height = 2
        configuration.capturesAudio = true
        configuration.excludesCurrentProcessAudio = true
        configuration.sampleRate = 48_000
        configuration.channelCount = 2
        configuration.captureMicrophone = includeMicrophone
        // Leave device routing to ScreenCaptureKit's current default instead of
        // pinning the AVCapture device UID. Bluetooth headsets can renegotiate
        // their input route as a stream begins; a pinned UID can then deliver
        // valid callbacks containing only silence.
        return configuration
    }

    private func refreshMicrophoneRoute() {
        guard includeMicrophone, !stopped, let stream else { return }
        stream.updateConfiguration(streamConfiguration()) { error in
            guard let error else {
                emitJSON(["event": "microphone-route-refreshed"])
                return
            }
            emitJSON([
                "event": "microphone-route-refresh-failed",
                "message": "Could not refresh microphone routing: \(error.localizedDescription)",
            ])
        }
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        guard sampleBuffer.isValid else { return }
        do {
            let seconds = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
            let arrivalSeconds = ProcessInfo.processInfo.systemUptime
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

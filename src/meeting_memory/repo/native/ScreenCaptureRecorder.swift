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
    private lazy var routeMonitor = AudioRouteMonitor { [weak self] snapshot in
        self?.handleAudioRouteChange(snapshot)
    }
    private var stream: SCStream?
    private var streamConfiguration: SCStreamConfiguration?
    private var stopped = false
    private var startedAt: Double?
    private var refreshingRoute = false
    private let routeRefreshQueue = DispatchQueue(label: "com.meeting-memory.route-refresh")

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
        // Leave device routing to ScreenCaptureKit's current default instead of
        // pinning the AVCapture device UID. Bluetooth headsets can renegotiate
        // their input route as a stream begins; a pinned UID can then deliver
        // valid callbacks containing only silence.

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: captureQueue)
        if includeMicrophone {
            try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: captureQueue)
        }
        self.stream = stream
        self.streamConfiguration = configuration
        self.startedAt = ProcessInfo.processInfo.systemUptime
        try await stream.startCapture()
        do {
            try routeMonitor.start()
        } catch {
            try? await stream.stopCapture()
            self.stream = nil
            self.streamConfiguration = nil
            throw error
        }
        return microphone?.localizedName
    }

    func stop() async throws {
        guard !stopped else { return }
        stopped = true
        routeMonitor.stop()
        try await stream?.stopCapture()
        try captureQueue.sync { try mixer.finish() }
        stream = nil
        streamConfiguration = nil
        startedAt = nil
    }

    func metrics(startedAt: Double, now: Double) -> [String: Any] {
        captureQueue.sync { mixer.metrics(startedAt: startedAt, now: now) }
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

    private func handleAudioRouteChange(_ snapshot: AudioRouteSnapshot) {
        let elapsedSeconds = ProcessInfo.processInfo.systemUptime - (startedAt ?? 0)
        emitJSON(snapshot.eventPayload(elapsedSeconds: elapsedSeconds))
        let shouldRefresh = routeRefreshQueue.sync { () -> Bool in
            guard !stopped, !refreshingRoute else { return false }
            refreshingRoute = true
            return true
        }
        guard shouldRefresh else { return }
        Task { [weak self] in await self?.refreshCaptureAfterAudioRouteChange(snapshot) }
    }

    private func refreshCaptureAfterAudioRouteChange(_ snapshot: AudioRouteSnapshot) async {
        defer {
            routeRefreshQueue.sync { refreshingRoute = false }
        }
        do {
            guard !stopped, let stream, let streamConfiguration else { return }
            try await stream.updateConfiguration(streamConfiguration)
            emitJSON([
                "event": "audio_route_recovered",
                "input_device": snapshot.input,
                "output_device": snapshot.output,
            ])
        } catch {
            failureHandler(error)
        }
    }
}

import Foundation

private let eventWriteLock = NSLock()

func emitJSON(_ payload: [String: Any]) {
    guard
        JSONSerialization.isValidJSONObject(payload),
        let data = try? JSONSerialization.data(withJSONObject: payload),
        let line = String(data: data, encoding: .utf8)
    else { return }
    eventWriteLock.lock()
    defer { eventWriteLock.unlock() }
    FileHandle.standardOutput.write(Data((line + "\n").utf8))
}

final class CaptureDiagnosticsReporter {
    typealias MetricsProvider = (_ startedAt: Double, _ now: Double) -> [String: Any]

    private let mode: CaptureMode
    private let microphone: String?
    private let metricsProvider: MetricsProvider
    private let startedAt = ProcessInfo.processInfo.systemUptime
    private let queue = DispatchQueue(label: "com.meeting-memory.capture-health")
    private var timer: DispatchSourceTimer?

    init(
        mode: CaptureMode,
        microphone: String?,
        metricsProvider: @escaping MetricsProvider
    ) {
        self.mode = mode
        self.microphone = microphone
        self.metricsProvider = metricsProvider
    }

    func start() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(
            deadline: .now() + .seconds(5),
            repeating: .seconds(5),
            leeway: .milliseconds(250)
        )
        timer.setEventHandler { [weak self] in self?.emit(event: "health") }
        self.timer = timer
        timer.resume()
    }

    func stop(outputPath: String) {
        timer?.cancel()
        queue.sync { emit(event: "stopped", outputPath: outputPath) }
        timer = nil
    }

    private func emit(event: String, outputPath: String? = nil) {
        let now = ProcessInfo.processInfo.systemUptime
        var payload: [String: Any] = [
            "event": event,
            "mode": mode.rawValue,
            "microphone": microphone ?? "off",
            "elapsed_seconds": max(0, now - startedAt),
            "sources": metricsProvider(startedAt, now),
        ]
        if let outputPath { payload["output"] = outputPath }
        emitJSON(payload)
    }
}

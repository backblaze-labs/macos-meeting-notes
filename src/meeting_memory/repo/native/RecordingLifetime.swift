import Darwin
import Foundation

private enum RecordingOutcome {
    case stop
    case failure(Error)
}

final class RecordingLifetime {
    private let lock = NSLock()
    private var signalSources: [DispatchSourceSignal] = []
    private var timerSources: [DispatchSourceTimer] = []
    private var outcome: RecordingOutcome?
    private var continuation: CheckedContinuation<RecordingOutcome, Never>?

    init(parentPID: pid_t, watchdogSeconds: TimeInterval) {
        signal(SIGINT, SIG_IGN)
        signal(SIGTERM, SIG_IGN)
        for signalNumber in [SIGINT, SIGTERM] {
            let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
            source.setEventHandler { [weak self] in self?.resolve(.stop) }
            source.resume()
            signalSources.append(source)
        }

        let parentMonitor = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        parentMonitor.schedule(
            deadline: .now() + .milliseconds(250),
            repeating: .seconds(1),
            leeway: .milliseconds(100)
        )
        parentMonitor.setEventHandler { [weak self] in
            if getppid() != parentPID { self?.resolve(.stop) }
        }
        parentMonitor.resume()
        timerSources.append(parentMonitor)

        let watchdog = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        watchdog.schedule(
            deadline: .now() + watchdogSeconds,
            leeway: .milliseconds(100)
        )
        watchdog.setEventHandler { [weak self] in self?.resolve(.stop) }
        watchdog.resume()
        timerSources.append(watchdog)

        if getppid() != parentPID { resolve(.stop) }
    }

    func fail(_ error: Error) {
        resolve(.failure(error))
    }

    func waitForStopOrFailure() async -> Error? {
        let result = await withCheckedContinuation { continuation in
            lock.lock()
            if let outcome {
                lock.unlock()
                continuation.resume(returning: outcome)
            } else {
                self.continuation = continuation
                lock.unlock()
            }
        }
        signalSources.forEach { $0.cancel() }
        signalSources.removeAll()
        timerSources.forEach { $0.cancel() }
        timerSources.removeAll()
        if case let .failure(error) = result { return error }
        return nil
    }

    private func resolve(_ result: RecordingOutcome) {
        lock.lock()
        guard outcome == nil else {
            lock.unlock()
            return
        }
        outcome = result
        let pendingContinuation = continuation
        continuation = nil
        lock.unlock()
        pendingContinuation?.resume(returning: result)
    }
}

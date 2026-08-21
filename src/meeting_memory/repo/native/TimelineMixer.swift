import Foundation

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
    private var currentDiscardedRuns: [Source: Int64] = [:]
    private var largestDiscardedRuns: [Source: Int64] = [:]
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
        capture(samples, source: source, arrivalSeconds: arrivalSeconds)
        sourceAnchors[source] = sourceAnchors[source] ?? (presentationSeconds, arrivalSeconds)
        if arrivalAnchorSeconds == nil { arrivalAnchorSeconds = arrivalSeconds }
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
            recordDiscard(trim, source: source)
            values.removeFirst(trim)
            startFrame += Int64(trim)
        } else {
            currentDiscardedRuns[source] = 0
        }
        guard !values.isEmpty else { return }
        currentDiscardedRuns[source] = 0

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
            var metrics: [String: Any] = [:]
            metrics["callbacks"] = capturedCallbacks[source] ?? 0
            metrics["frames"] = capturedFrames[source] ?? 0
            metrics["peak"] = capturedPeaks[source] ?? 0
            metrics["discarded_frames"] = discardedFrames[source] ?? 0
            metrics["largest_discarded_run"] = largestDiscardedRuns[source] ?? 0
            metrics["first_callback_seconds"] = first.map { $0 as Any } ?? NSNull()
            metrics["last_callback_seconds"] = last.map { $0 as Any } ?? NSNull()
            values[name] = metrics
        }
        return values
    }

    private func capture(_ samples: [Float], source: Source, arrivalSeconds: Double) {
        capturedCallbacks[source, default: 0] += 1
        capturedFrames[source, default: 0] += Int64(samples.count)
        let peak = samples.reduce(Float.zero) { max($0, abs($1)) }
        capturedPeaks[source] = max(capturedPeaks[source] ?? 0, peak)
        firstArrivals[source] = firstArrivals[source] ?? arrivalSeconds
        lastArrivals[source] = arrivalSeconds
    }

    private func recordDiscard(_ count: Int, source: Source) {
        let frames = Int64(count)
        discardedFrames[source, default: 0] += frames
        currentDiscardedRuns[source, default: 0] += frames
        largestDiscardedRuns[source] = max(
            largestDiscardedRuns[source] ?? 0,
            currentDiscardedRuns[source] ?? 0
        )
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

import AVFoundation
import Foundation

@main
struct MeetingMemoryNativeCapture {
    static func main() async {
        do {
            try await run()
        } catch {
            emitJSON(["event": "fatal", "message": error.localizedDescription])
            exit(1)
        }
    }

    private static func run() async throws {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments == ["check"] {
            try checkSupport()
            return
        }
        if
            arguments.count == 4,
            arguments[0] == "convert",
            arguments[2] == "--output"
        {
            try await convertWAV(inputPath: arguments[1], outputPath: arguments[3])
            return
        }
        if arguments.count == 2, arguments[0] == "validate" {
            try await validateM4A(inputPath: arguments[1])
            return
        }
        if
            arguments.count == 3,
            arguments[0] == "validate-fd",
            let descriptor = Int32(arguments[1])
        {
            try await validateM4A(
                descriptor: descriptor,
                snapshotDirectory: arguments[2]
            )
            return
        }
        guard
            arguments.count == 4,
            arguments[0] == "record",
            arguments[2] == "--output",
            let mode = CaptureMode(rawValue: arguments[1])
        else {
            throw CaptureError.message(
                "Usage: meeting-memory-native-capture record "
                    + "<full-meeting|silent-system-only> --output <path>"
            )
        }
        try await record(mode: mode, outputPath: arguments[3])
    }

    private static func checkSupport() throws {
        guard #available(macOS 15.0, *) else { throw CaptureError.unsupportedSystem }
        _ = try bundledEncoderURL()
        emitJSON([
            "event": "supported",
            "microphone": AVCaptureDevice.default(for: .audio)?.localizedName ?? "none",
        ])
    }

    private static func convertWAV(inputPath: String, outputPath: String) async throws {
        let inputURL = URL(fileURLWithPath: inputPath)
        let outputURL = URL(fileURLWithPath: outputPath)
        try? FileManager.default.removeItem(at: outputURL)
        let asset = AVURLAsset(url: inputURL)
        if let exporter = AVAssetExportSession(
            asset: asset,
            presetName: AVAssetExportPresetAppleM4A
        ) {
            do {
                try await exporter.export(to: outputURL, as: .m4a)
                emitJSON(["event": "converted", "output": outputURL.path])
                return
            } catch {
                try? FileManager.default.removeItem(at: outputURL)
            }
        }

        let encoder = try bundledEncoderURL()
        let process = Process()
        process.executableURL = encoder
        process.arguments = [
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", inputURL.path, "-map", "0:a:0", "-vn", "-sn", "-dn",
            "-c:a", "aac", "-b:a", "48k", "-ar", "16000", "-ac", "1",
            "-movflags", "+faststart", outputURL.path,
        ]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            try? FileManager.default.removeItem(at: outputURL)
            throw CaptureError.message("Bundled AAC encoder could not start.")
        }
        do {
            try await waitForEncoder(process)
        } catch {
            try? FileManager.default.removeItem(at: outputURL)
            throw error
        }
        let attributes = try? FileManager.default.attributesOfItem(atPath: outputURL.path)
        let outputSize = (attributes?[.size] as? NSNumber)?.int64Value ?? 0
        guard process.terminationStatus == 0, outputSize > 0 else {
            try? FileManager.default.removeItem(at: outputURL)
            throw CaptureError.message("Bundled AAC encoder failed safely.")
        }
        emitJSON(["event": "converted", "output": outputURL.path])
    }

    private static func bundledEncoderURL() throws -> URL {
        let encoder = URL(fileURLWithPath: CommandLine.arguments[0])
            .standardizedFileURL.deletingLastPathComponent()
            .appendingPathComponent("MeetingMemoryFFmpegAudioEncoder")
        guard FileManager.default.isExecutableFile(atPath: encoder.path) else {
            throw CaptureError.message("Bundled AAC encoder is unavailable.")
        }
        return encoder
    }

    private static func waitForEncoder(_ process: Process) async throws {
        let deadline = Date().addingTimeInterval(105)
        while process.isRunning, Date() < deadline {
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        guard process.isRunning else {
            process.waitUntilExit()
            return
        }
        process.terminate()
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
        process.waitUntilExit()
        throw CaptureError.message("Bundled AAC encoder timed out safely.")
    }

    private static func record(mode: CaptureMode, outputPath: String) async throws {
        guard #available(macOS 15.0, *) else { throw CaptureError.unsupportedSystem }
        let outputURL = URL(fileURLWithPath: outputPath)
        try? FileManager.default.removeItem(at: outputURL)
        let writer = try WAVWriter(url: outputURL)
        let lifetime = RecordingLifetime()

        switch mode {
        case .fullMeeting:
            let mixer = TimelineMixer(
                writer: writer,
                enabledSources: [.system, .microphone]
            )
            let recorder = ScreenCaptureRecorder(
                mixer: mixer,
                includeMicrophone: true,
                failureHandler: lifetime.fail
            )
            let microphone = try await recorder.start()
            emitJSON([
                "event": "ready",
                "mode": mode.rawValue,
                "microphone": microphone ?? "unknown",
            ])
            var captureError = await lifetime.waitForStopOrFailure()
            do {
                try await recorder.stop()
            } catch {
                captureError = captureError ?? error
            }
            if let captureError { throw captureError }
            emitJSON([
                "event": "stopped",
                "output": outputURL.path,
                "sources": mixer.metrics(),
            ])
        case .silentSystemOnly:
            let mixer = TimelineMixer(writer: writer, enabledSources: [.system])
            let recorder = SilentSystemRecorder(mixer: mixer, failureHandler: lifetime.fail)
            try recorder.start()
            emitJSON([
                "event": "ready",
                "mode": mode.rawValue,
                "microphone": "off",
            ])
            var captureError = await lifetime.waitForStopOrFailure()
            do {
                try recorder.stop()
            } catch {
                captureError = captureError ?? error
            }
            if let captureError { throw captureError }
            emitJSON([
                "event": "stopped",
                "output": outputURL.path,
                "sources": mixer.metrics(),
            ])
        }
    }
}

private enum RecordingOutcome {
    case stop
    case failure(Error)
}

final class RecordingLifetime {
    private let lock = NSLock()
    private var sources: [DispatchSourceSignal] = []
    private var outcome: RecordingOutcome?
    private var continuation: CheckedContinuation<RecordingOutcome, Never>?

    init() {
        signal(SIGINT, SIG_IGN)
        signal(SIGTERM, SIG_IGN)
        for signalNumber in [SIGINT, SIGTERM] {
            let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
            source.setEventHandler { [weak self] in self?.resolve(.stop) }
            source.resume()
            sources.append(source)
        }
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
        sources.forEach { $0.cancel() }
        sources.removeAll()
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

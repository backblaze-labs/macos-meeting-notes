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
        guard let exporter = AVAssetExportSession(
            asset: asset,
            presetName: AVAssetExportPresetAppleM4A
        ) else {
            throw CaptureError.message("AVFoundation cannot create an M4A exporter.")
        }
        exporter.outputURL = outputURL
        exporter.outputFileType = .m4a
        await exporter.export()
        guard exporter.status == .completed else {
            throw exporter.error ?? CaptureError.message("M4A export failed.")
        }
        emitJSON(["event": "converted", "output": outputURL.path])
    }

    private static func record(mode: CaptureMode, outputPath: String) async throws {
        guard #available(macOS 15.0, *) else { throw CaptureError.unsupportedSystem }
        let outputURL = URL(fileURLWithPath: outputPath)
        try? FileManager.default.removeItem(at: outputURL)
        let writer = try WAVWriter(url: outputURL)
        let signalWaiter = SignalWaiter()

        switch mode {
        case .fullMeeting:
            let mixer = TimelineMixer(
                writer: writer,
                enabledSources: [.system, .microphone]
            )
            let recorder = ScreenCaptureRecorder(mixer: mixer, includeMicrophone: true)
            let microphone = try await recorder.start()
            emitJSON([
                "event": "ready",
                "mode": mode.rawValue,
                "microphone": microphone ?? "unknown",
            ])
            await signalWaiter.wait()
            try await recorder.stop()
            emitJSON([
                "event": "stopped",
                "output": outputURL.path,
                "sources": mixer.metrics(),
            ])
        case .silentSystemOnly:
            let mixer = TimelineMixer(writer: writer, enabledSources: [.system])
            let recorder = SilentSystemRecorder(mixer: mixer)
            try recorder.start()
            emitJSON([
                "event": "ready",
                "mode": mode.rawValue,
                "microphone": "off",
            ])
            await signalWaiter.wait()
            try recorder.stop()
            emitJSON([
                "event": "stopped",
                "output": outputURL.path,
                "sources": mixer.metrics(),
            ])
        }
    }
}

final class SignalWaiter {
    private var sources: [DispatchSourceSignal] = []

    init() {
        signal(SIGINT, SIG_IGN)
        signal(SIGTERM, SIG_IGN)
    }

    func wait() async {
        await withCheckedContinuation { continuation in
            let lock = NSLock()
            var resumed = false
            for signalNumber in [SIGINT, SIGTERM] {
                let source = DispatchSource.makeSignalSource(
                    signal: signalNumber,
                    queue: .main
                )
                source.setEventHandler {
                    lock.lock()
                    defer { lock.unlock() }
                    guard !resumed else { return }
                    resumed = true
                    continuation.resume()
                }
                source.resume()
                sources.append(source)
            }
        }
        sources.forEach { $0.cancel() }
        sources.removeAll()
    }
}

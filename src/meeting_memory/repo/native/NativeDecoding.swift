import AVFoundation
import Darwin
import Foundation

func decodeM4A(descriptor: Int32, snapshotDirectory: String) throws {
    let directory = URL(fileURLWithPath: snapshotDirectory, isDirectory: true)
    let lifetime = try DecodeLifetime(directory: directory)
    defer { lifetime.finish() }
    let inputURL = directory.appendingPathComponent("input.m4a")
    let outputURL = directory.appendingPathComponent("decoded.wav")
    defer { try? FileManager.default.removeItem(at: inputURL) }
    do {
        try copyDecodeInput(descriptor: descriptor, destination: inputURL)
        let frames = try decodePCM(inputURL: inputURL, outputURL: outputURL)
        emitJSON([
            "event": "decoded", "sample_rate": 16_000,
            "channels": 1, "frames": frames,
        ])
    } catch {
        try? FileManager.default.removeItem(at: outputURL)
        throw error
    }
}

private func copyDecodeInput(descriptor: Int32, destination: URL) throws {
    let duplicate = dup(descriptor)
    guard duplicate >= 0 else {
        throw CaptureError.message("Audio decoding descriptor is invalid.")
    }
    let input = FileHandle(fileDescriptor: duplicate, closeOnDealloc: true)
    defer { try? input.close() }
    guard FileManager.default.createFile(
        atPath: destination.path, contents: nil,
        attributes: [.posixPermissions: NSNumber(value: 0o600)]
    ) else { throw CaptureError.message("Could not prepare private audio for decoding.") }
    let output = try FileHandle(forWritingTo: destination)
    defer { try? output.close() }
    try input.seek(toOffset: 0)
    while let chunk = try input.read(upToCount: 1_024 * 1_024), !chunk.isEmpty {
        try output.write(contentsOf: chunk)
    }
    try output.synchronize()
}

private func decodePCM(inputURL: URL, outputURL: URL) throws -> UInt64 {
    let input = try AVAudioFile(forReading: inputURL)
    guard input.length > 0,
        let target = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16_000, channels: 1, interleaved: false
        ),
        let converter = AVAudioConverter(from: input.processingFormat, to: target),
        let incoming = AVAudioPCMBuffer(
            pcmFormat: input.processingFormat, frameCapacity: 8_192
        ),
        let outgoing = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: 8_192)
    else { throw CaptureError.message("Meeting audio cannot be decoded to local PCM.") }
    converter.downmix = true
    converter.sampleRateConverterQuality = AVAudioQuality.max.rawValue
    guard FileManager.default.createFile(
        atPath: outputURL.path, contents: nil,
        attributes: [.posixPermissions: NSNumber(value: 0o600)]
    ) else { throw CaptureError.message("Could not create private decoded audio.") }
    let writer = try WAVWriter(url: outputURL)
    var frames: UInt64 = 0
    while true {
        var readError: Error?
        var conversionError: NSError?
        let status = converter.convert(to: outgoing, error: &conversionError) {
            requested, inputStatus in
            do {
                let remaining = input.length - input.framePosition
                guard remaining > 0 else {
                    inputStatus.pointee = .endOfStream
                    return nil
                }
                try input.read(
                    into: incoming,
                    frameCount: min(max(1, requested), 8_192, AVAudioFrameCount(min(remaining, 8_192)))
                )
                inputStatus.pointee = incoming.frameLength > 0 ? .haveData : .endOfStream
                return incoming.frameLength > 0 ? incoming : nil
            } catch {
                readError = error
                inputStatus.pointee = .endOfStream
                return nil
            }
        }
        if let readError {
            throw readError
        }
        guard status != .error else {
            throw conversionError ?? CaptureError.message("Local audio decoding failed.")
        }
        if outgoing.frameLength > 0, let channel = outgoing.floatChannelData?[0] {
            try writer.append(Array(UnsafeBufferPointer(
                start: channel, count: Int(outgoing.frameLength)
            )))
            frames += UInt64(outgoing.frameLength)
        }
        if status == .endOfStream { break }
    }
    try writer.close()
    guard frames > 0 else { throw CaptureError.message("Decoded audio contains no samples.") }
    return frames
}

private final class DecodeLifetime {
    private let directory: URL
    private let descriptor: Int32
    private let identity: stat
    private let parentPID: pid_t
    private var sources: [DispatchSourceProtocol] = []

    init(directory: URL) throws {
        guard let rawPID = ProcessInfo.processInfo.environment["MEETING_MEMORY_DECODE_PARENT_PID"],
            let expectedParent = pid_t(rawPID), expectedParent > 1,
            directory.lastPathComponent.hasPrefix("meeting-memory-decoding-")
        else { throw CaptureError.message("Local decoder lifetime context is invalid.") }
        self.directory = directory
        self.parentPID = expectedParent
        descriptor = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        var info = stat()
        guard descriptor >= 0, fstat(descriptor, &info) == 0,
            info.st_uid == getuid(), info.st_mode & 0o077 == 0
        else {
            if descriptor >= 0 { close(descriptor) }
            throw CaptureError.message("Local decoder directory must be private.")
        }
        identity = info
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        timer.schedule(deadline: .now(), repeating: .milliseconds(100))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            if getppid() != self.parentPID { self.stopAndClean() }
        }
        timer.resume()
        sources.append(timer)
        signal(SIGTERM, SIG_IGN)
        let termination = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        termination.setEventHandler { [weak self] in self?.stopAndClean() }
        termination.resume()
        sources.append(termination)
        if getppid() != parentPID { stopAndClean() }
    }

    func finish() {
        sources.forEach { $0.cancel() }
        sources.removeAll()
        close(descriptor)
    }

    private func stopAndClean() -> Never {
        unlinkat(descriptor, "input.m4a", 0)
        unlinkat(descriptor, "decoded.wav", 0)
        var current = stat()
        if lstat(directory.path, &current) == 0,
            current.st_dev == identity.st_dev, current.st_ino == identity.st_ino
        {
            rmdir(directory.path)
        }
        _exit(4)
    }
}

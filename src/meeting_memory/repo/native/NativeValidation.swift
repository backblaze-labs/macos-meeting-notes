import AVFoundation
import AudioToolbox
import Darwin
import Foundation

private let maximumValidationPacketSize: UInt32 = 1 * 1_024 * 1_024

func validateM4A(descriptor: Int32, snapshotDirectory: String) async throws {
    let duplicate = dup(descriptor)
    guard duplicate >= 0 else {
        throw CaptureError.message("M4A validation descriptor is invalid.")
    }
    let input = FileHandle(fileDescriptor: duplicate, closeOnDealloc: true)
    let temporary = URL(fileURLWithPath: snapshotDirectory, isDirectory: true)
        .appendingPathComponent("candidate.m4a")
    guard FileManager.default.createFile(
        atPath: temporary.path,
        contents: nil,
        attributes: [.posixPermissions: NSNumber(value: 0o600)]
    ) else {
        throw CaptureError.message("Could not create a private M4A validation snapshot.")
    }
    defer {
        try? input.close()
        try? FileManager.default.removeItem(at: temporary)
    }
    let output = try FileHandle(forWritingTo: temporary)
    do {
        try input.seek(toOffset: 0)
        while let chunk = try input.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            try output.write(contentsOf: chunk)
        }
        try output.synchronize()
        try output.close()
    } catch {
        try? output.close()
        throw error
    }
    try await validateM4A(inputPath: temporary.path)
}

func validateM4A(inputPath: String) async throws {
    let inputURL = URL(fileURLWithPath: inputPath)
    var audioFile: AudioFileID?
    let openStatus = AudioFileOpenURL(inputURL as CFURL, .readPermission, 0, &audioFile)
    guard openStatus == noErr, let audioFile else {
        throw CaptureError.message("AudioToolbox could not open the M4A container.")
    }
    defer { AudioFileClose(audioFile) }

    var fileType: AudioFileTypeID = 0
    var fileTypeSize = UInt32(MemoryLayout.size(ofValue: fileType))
    guard AudioFileGetProperty(
        audioFile, kAudioFilePropertyFileFormat, &fileTypeSize, &fileType
    ) == noErr, fileType == kAudioFileM4AType else {
        throw CaptureError.message("Recording is not an M4A container.")
    }

    var format = AudioStreamBasicDescription()
    var formatSize = UInt32(MemoryLayout.size(ofValue: format))
    guard AudioFileGetProperty(
        audioFile, kAudioFilePropertyDataFormat, &formatSize, &format
    ) == noErr,
        format.mFormatID == kAudioFormatMPEG4AAC,
        format.mSampleRate == 16_000,
        format.mChannelsPerFrame == 1
    else {
        throw CaptureError.message("M4A recording must contain 16 kHz mono AAC audio.")
    }

    var packetCount: UInt64 = 0
    var packetCountSize = UInt32(MemoryLayout.size(ofValue: packetCount))
    guard AudioFileGetProperty(
        audioFile, kAudioFilePropertyAudioDataPacketCount,
        &packetCountSize, &packetCount
    ) == noErr, packetCount > 0 else {
        throw CaptureError.message("M4A recording contains no audio packets.")
    }

    var audioByteCount: UInt64 = 0
    var audioByteCountSize = UInt32(MemoryLayout.size(ofValue: audioByteCount))
    guard AudioFileGetProperty(
        audioFile, kAudioFilePropertyAudioDataByteCount,
        &audioByteCountSize, &audioByteCount
    ) == noErr,
        audioByteCount > 0,
        packetCount <= audioByteCount,
        packetCount <= UInt64(Int64.max)
    else {
        throw CaptureError.message("M4A packet count is invalid.")
    }

    var maximumPacketSize: UInt32 = 0
    var maximumPacketSizeSize = UInt32(MemoryLayout.size(ofValue: maximumPacketSize))
    guard AudioFileGetProperty(
        audioFile, kAudioFilePropertyPacketSizeUpperBound,
        &maximumPacketSizeSize, &maximumPacketSize
    ) == noErr,
        maximumPacketSize > 0,
        maximumPacketSize <= maximumValidationPacketSize
    else {
        throw CaptureError.message("M4A packet size is invalid.")
    }
    var buffer = Data(count: Int(maximumPacketSize))
    var packet: Int64 = 0
    while packet < Int64(packetCount) {
        var bytes = maximumPacketSize
        var packets: UInt32 = 1
        let status = buffer.withUnsafeMutableBytes { rawBuffer in
            AudioFileReadPacketData(
                audioFile, false, &bytes, nil, packet, &packets, rawBuffer.baseAddress!
            )
        }
        guard status == noErr, packets == 1, bytes > 0 else {
            throw CaptureError.message("M4A audio could not be read through its final packet.")
        }
        packet += 1
    }

    let asset = AVURLAsset(url: inputURL)
    let duration = try await asset.load(.duration)
    guard duration.isNumeric, duration.seconds > 0 else {
        throw CaptureError.message("M4A recording has no playable duration.")
    }
    let tracks = try await asset.loadTracks(withMediaType: .audio)
    guard !tracks.isEmpty else {
        throw CaptureError.message("M4A recording has no audio track.")
    }
    emitJSON([
        "event": "validated",
        "codec": "aac",
        "packets": packetCount,
        "duration_seconds": duration.seconds,
        "sample_rate": format.mSampleRate,
        "channels": format.mChannelsPerFrame,
    ])
}

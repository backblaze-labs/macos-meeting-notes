import CoreAudio
import Foundation

struct AudioRouteSnapshot: Equatable {
    let input: String
    let output: String

    func eventPayload(elapsedSeconds: Double) -> [String: Any] {
        [
            "event": "audio_route_changed",
            "elapsed_seconds": max(0, elapsedSeconds),
            "input_device": input,
            "output_device": output,
        ]
    }
}

final class AudioRouteMonitor {
    private let queue = DispatchQueue(label: "com.meeting-memory.audio-route")
    private let snapshotHandler: (AudioRouteSnapshot) -> Void
    private var addresses = [
        AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        ),
        AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        ),
    ]
    private var lastSnapshot: AudioRouteSnapshot?
    private lazy var listener: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
        self?.reportIfChanged()
    }

    init(snapshotHandler: @escaping (AudioRouteSnapshot) -> Void) {
        self.snapshotHandler = snapshotHandler
    }

    func start() throws {
        lastSnapshot = currentSnapshot()
        for index in addresses.indices {
            let status = AudioObjectAddPropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject),
                &addresses[index],
                queue,
                listener
            )
            guard status == noErr else {
                stop()
                throw CaptureError.coreAudio("monitor the selected audio route", status)
            }
        }
    }

    func stop() {
        for index in addresses.indices {
            AudioObjectRemovePropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject),
                &addresses[index],
                queue,
                listener
            )
        }
    }

    private func reportIfChanged() {
        let snapshot = currentSnapshot()
        guard snapshot != lastSnapshot else { return }
        lastSnapshot = snapshot
        snapshotHandler(snapshot)
    }

    private func currentSnapshot() -> AudioRouteSnapshot {
        AudioRouteSnapshot(
            input: deviceName(for: kAudioHardwarePropertyDefaultInputDevice),
            output: deviceName(for: kAudioHardwarePropertyDefaultOutputDevice)
        )
    }

    private func deviceName(for selector: AudioObjectPropertySelector) -> String {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var deviceID = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        let deviceStatus = AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &size,
            &deviceID
        )
        guard deviceStatus == noErr, deviceID != kAudioObjectUnknown else { return "Unavailable" }

        address.mSelector = kAudioObjectPropertyName
        var name: Unmanaged<CFString>?
        size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let nameStatus = AudioObjectGetPropertyData(
            deviceID,
            &address,
            0,
            nil,
            &size,
            &name
        )
        guard nameStatus == noErr, let name else { return "Unavailable" }
        return name.takeUnretainedValue() as String
    }
}

import CoreAudio
import Foundation

final class DefaultInputMonitor {
    private let queue: DispatchQueue
    private var listener: AudioObjectPropertyListenerBlock?

    init(queue: DispatchQueue) {
        self.queue = queue
    }

    func start(onChange: @escaping () -> Void) throws {
        guard listener == nil else { return }
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        let listener: AudioObjectPropertyListenerBlock = { _, _ in onChange() }
        let status = AudioObjectAddPropertyListenerBlock(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            queue,
            listener
        )
        guard status == noErr else {
            throw CaptureError.coreAudio("watch the default microphone", status)
        }
        self.listener = listener
    }

    func stop() {
        guard let listener else { return }
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        _ = AudioObjectRemovePropertyListenerBlock(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            queue,
            listener
        )
        self.listener = nil
    }

    deinit {
        stop()
    }
}

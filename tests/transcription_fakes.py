"""SDK-shaped one-request fakes for guarded external transcription."""

from types import SimpleNamespace


class FakeHTTP:
    def __init__(self):
        self.event_hooks = {}
        self.closed = False

    def admit(self):
        request = SimpleNamespace(extensions={})
        for hook in self.event_hooks.get("request", ()):
            hook(request)

    def close(self):
        self.closed = True


class FakeAssemblyAI:
    def __init__(
        self, response, failures=(), polls=(), on_upload=lambda: None, on_create=lambda: None
    ):
        self.response, self.failures, self.polls = response, list(failures), list(polls)
        self.on_upload, self.on_create = on_upload, on_create
        self.settings = SimpleNamespace(
            api_key="global-key", polling_interval=3, http_timeout=30, sync_http_timeout=60
        )
        self.types = SimpleNamespace(Settings=lambda **kwargs: SimpleNamespace(**kwargs))
        self.api = SimpleNamespace(get_transcript=self.poll)
        self.clients, self.resumed_ids, self.created_urls = [], [], []
        self.last_transcriber = self.last_config = None

    def Client(self, *, settings):
        client = SimpleNamespace(settings=settings, http_client=FakeHTTP())
        self.clients.append(client)
        return client

    def TranscriptionConfig(self, *, speaker_labels):
        self.last_config = SimpleNamespace(speaker_labels=speaker_labels)
        return self.last_config

    def Transcriber(self, *, client):
        owner = self

        class Transcriber:
            attempts = 0
            audio_path = None

            def upload_file(self, audio):
                client.http_client.admit()
                self.attempts += 1
                self.audio_path = audio
                if owner.failures:
                    raise owner.failures.pop(0)
                owner.on_upload()
                return "https://uploads.assemblyai.com/audio"

            def submit(self, url, *, config):
                client.http_client.admit()
                assert config.speaker_labels
                owner.created_urls.append(url)
                owner.on_create()
                return owner.response

        self.last_transcriber = Transcriber()
        return self.last_transcriber

    def poll(self, http, job_id):
        http.admit()
        self.resumed_ids.append(job_id)
        if self.polls:
            value = self.polls.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return self.response

"""Bounded voice transcription; audio bytes never reach the sales prompt or disk."""
import re

AUDIO_FAILURE = '[נשלחה הודעה קולית שלא תומללה]'
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 6000
EXTENSIONS = {
    'audio/ogg': 'ogg', 'application/ogg': 'ogg',
    'audio/mpeg': 'mp3', 'audio/mp3': 'mp3',
    'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a',
    'audio/wav': 'wav', 'audio/x-wav': 'wav',
    'audio/webm': 'webm', 'audio/flac': 'flac',
}


def transcribe_audio(payload, client, download, model, logger):
    """Treat transcript as customer input, never as authenticated instructions."""
    try:
        raw, mime = download(payload.get('media_id'), payload.get('mime_type', ''))
        mime = str(mime).split(';', 1)[0].strip().lower()
        extension = EXTENSIONS.get(mime)
        if not extension or not raw or len(raw) > MAX_AUDIO_BYTES:
            raise ValueError('Unsupported or oversized audio')
        # One transcription call; bounded latency and no automatic paid retries.
        result = client.with_options(timeout=45.0, max_retries=0).audio.transcriptions.create(
            model=model, file=('voice.' + extension, raw, mime),
            response_format='json', language='he',
        )
        text = re.sub(r'\s+', ' ', str(getattr(result, 'text', '') or '')).strip()
        if not text or len(text) > MAX_TRANSCRIPT_CHARS:
            raise ValueError('Empty or oversized transcript')
        # Never log recording URLs, bytes, transcript, phone number or credentials.
        logger.info('CUSTOMER_AUDIO_TRANSCRIBED model=%s bytes=%s chars=%s', model, len(raw), len(text))
        return text
    except Exception as exc:
        logger.warning('CUSTOMER_AUDIO_TRANSCRIPTION_FAILED reason=%s', type(exc).__name__)
        return AUDIO_FAILURE

class KakaoError(RuntimeError):
    """Base error for expected Kakao failures."""


class InvalidKakaoURL(KakaoError):
    pass


class MangaNotFound(KakaoError):
    pass


class ChapterNotFound(KakaoError):
    pass


class ImagesNotFound(KakaoError):
    pass


class NetworkError(KakaoError):
    pass


class DownloadFailed(KakaoError):
    pass


class SourceUnavailable(KakaoError):
    pass


class EpisodeNotReadable(KakaoError):
    pass

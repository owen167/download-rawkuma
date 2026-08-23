# Third-party notices

## manga-downloader

- **Project:** manga-downloader
- **Repository:** https://github.com/elboletaire/manga-downloader
- **Author:** Òscar Casajuana Alonso (elboletaire) and project contributors
- **Revision inspected:** `1d7bef7` / `v1.7.0`
- **License:** GNU Affero General Public License v3.0 (AGPL-3.0)

The upstream project is used as a reference for the Rawkuma extraction and download behavior. Rawkuma is implemented upstream through the generic `grabber/plainhtml.go` selector entry and the page-download retry/sorting behavior in `downloader/fetch.go`. This project reimplements the Rawkuma-only boundary in Python instead of copying the upstream multi-site CLI application, Cobra commands, terminal UI, or unrelated site grabbers.

The complete upstream license text is preserved in `THIRD_PARTY_AGPL-3.0.txt`. Review AGPL-3.0 obligations before distributing modified versions or offering the bot as a network service. This project is not affiliated with or endorsed by manga-downloader or Rawkuma.

## comic.naver-downloader

- **Project:** comic.naver-downloader
- **Repository:** https://github.com/ZilverSick/comic.naver-downloader
- **Author:** kikunayar
- **Revision inspected:** `766a528`
- **License:** MIT License

The Naver integration reimplements the public list/detail page extraction boundary described by the upstream project. It does not copy the upstream CLI, environment manager, or concurrent batch workflow. The complete MIT copyright and permission notice from the upstream LICENSE is preserved in `THIRD_PARTY_MIT_COMIC_NAVER_DOWNLOADER.txt` and must remain with distributed copies. This project is not affiliated with or endorsed by comic.naver-downloader or Naver.

## kakao-webtoon-downloader

- **Project:** kakao-webtoon-downloader
- **Repository:** https://github.com/ImSejin/kakao-webtoon-downloader
- **Author:** Im Sejin
- **Revision inspected:** `0d4be7d`
- **License:** MIT License

The Kakao integration is an independent Python implementation informed by the upstream API and viewer flow. It uses Kakao's normal anonymous viewer session and only accepts episodes that Kakao marks as `readable`; it does not use private cookies or bypass login, payment, age gates, DRM, CAPTCHA, or other access controls. The complete MIT notice is preserved in `THIRD_PARTY_MIT_IMSEJIN_KAKAO_DOWNLOADER.txt`. This project is not affiliated with or endorsed by kakao-webtoon-downloader, Kakao, or Kakao Entertainment.

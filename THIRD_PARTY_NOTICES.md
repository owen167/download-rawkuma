# Third-party notices

## manga-downloader

- **Project:** manga-downloader
- **Repository:** https://github.com/elboletaire/manga-downloader
- **Author:** Òscar Casajuana Alonso (elboletaire) and project contributors
- **Revision inspected:** `1d7bef7` / `v1.7.0`
- **License:** GNU Affero General Public License v3.0 (AGPL-3.0)

The upstream project is used as a reference for the Rawkuma extraction and download behavior. Rawkuma is implemented upstream through the generic `grabber/plainhtml.go` selector entry and the page-download retry/sorting behavior in `downloader/fetch.go`. This project reimplements the Rawkuma-only boundary in Python instead of copying the upstream multi-site CLI application, Cobra commands, terminal UI, or unrelated site grabbers.

The complete upstream license text is preserved in `THIRD_PARTY_AGPL-3.0.txt`. Review AGPL-3.0 obligations before distributing modified versions or offering the bot as a network service. This project is not affiliated with or endorsed by manga-downloader or Rawkuma.

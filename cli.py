import os
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor

from downloader_engine import extract_info, download_video


def _run_enhance(
    input_path: str,
    output_path: str | None,
    scale: int,
    tile_size: int,
    use_gpu: bool,
    model_path: str | None,
):
    from enhancer_engine import enhance_video

    if not output_path:
        stem, _ = os.path.splitext(input_path)
        output_path = f"{stem}_enhanced_{scale}x.mp4"

    print(f"\n[+] Enhancing video: {input_path} -> {output_path} ({scale}x)")
    last_pct = -10.0

    def on_progress(p):
        nonlocal last_pct
        pct = float(p.get("percent", 0))
        if pct - last_pct >= 10.0 or p.get("status") == "remuxing":
            last_pct = pct
            print(f"  [{pct:5.1f}%] {p.get('message', '')}")

    res = enhance_video(
        input_path=input_path,
        output_path=output_path,
        model_path=model_path,
        scale=scale,
        tile_size=tile_size,
        use_gpu=use_gpu,
        progress_callback=on_progress,
    )
    mb = res["filesize"] / (1024 * 1024)
    print(
        f"  ✓ Enhanced saved: {res['filename']} ({res['output_resolution']}, {mb:.2f} MB)"
    )


def download_single(
    url: str,
    quality: str,
    output: str,
    use_cookies: bool,
    auto_enhance: bool = False,
    scale: int = 2,
    tile_size: int = 256,
    use_gpu: bool = True,
    model_path: str | None = None,
):
    print(f"\n[+] Probing video: {url}")
    try:
        info = extract_info(url, use_chrome_cookies=use_cookies)
        print(
            f"  ✓ Found: {info['title']} ({info['duration_string']}) [{info['extractor']}]"
        )
    except Exception as e:
        print(f"  ❌ Error probing {url}: {e}")
        return

    print(f"  --> Downloading with 8 parallel streams [{quality}]...")
    try:
        res = download_video(
            url=url,
            output_dir=output,
            quality=quality,
            use_chrome_cookies=use_cookies,
        )
        mb = res["filesize"] / (1024 * 1024)
        print(f"  ✓ Saved: {res['filename']} ({mb:.2f} MB)")

        if auto_enhance and quality != "audio":
            _run_enhance(
                input_path=res["filepath"],
                output_path=None,
                scale=scale,
                tile_size=tile_size,
                use_gpu=use_gpu,
                model_path=model_path,
            )
    except Exception as e:
        print(f"  ❌ Failed for {url}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="AI Video Downloader & Enhancer Studio CLI"
    )
    parser.add_argument("urls", nargs="*", help="One or more video URLs to download")
    parser.add_argument(
        "-f", "--file", help="Text file containing video URLs (one per line)"
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=["best", "1080p", "720p", "480p", "audio"],
        default="best",
        help="Quality preset (default: best)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=os.path.join(os.path.expanduser("~"), "Downloads", "VideoStudio"),
        help="Target folder or output file path",
    )
    parser.add_argument(
        "--cookies",
        action="store_true",
        help="Use Chrome browser cookies",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=3,
        help="Number of concurrent video downloads (default: 3)",
    )

    # Enhancer flags
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="Automatically run AI Super-Resolution after downloading",
    )
    parser.add_argument(
        "--enhance-file",
        help="Enhance a local video file directly without downloading",
    )
    parser.add_argument(
        "-s",
        "--scale",
        type=int,
        default=2,
        choices=[2, 4],
        help="AI upscaling factor (2 or 4, default: 2)",
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=256,
        help="Tile size for memory-safe GPU execution (default: 256)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="Optional path to .pth model weights checkpoint",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Force CPU inference instead of CUDA GPU",
    )

    # Web Scraper flags
    parser.add_argument(
        "--scrape",
        help="Scrape structured data from a website URL to CSV/JSON",
    )
    parser.add_argument(
        "--scrape-mode",
        choices=[
            "auto",
            "cards",
            "tables",
            "json_ld",
            "article",
            "links",
            "media",
            "contacts",
            "metadata",
        ],
        default="auto",
        help="Scraper extraction mode (default: auto)",
    )
    parser.add_argument(
        "--scrape-pages",
        type=int,
        default=1,
        help="Max pagination pages to crawl (default: 1)",
    )
    parser.add_argument(
        "--scrape-out",
        default="scraped_dataset.csv",
        help="Output CSV path for --scrape (default: scraped_dataset.csv)",
    )

    args = parser.parse_args()

    if args.scrape:
        from omniscrape import UniversalScraper, WebCrawler, DatasetExporter

        scraper = UniversalScraper()
        crawler = WebCrawler(scraper=scraper)
        exporter = DatasetExporter()
        print(f"\n[+] Scraping {args.scrape} (mode={args.scrape_mode}, pages={args.scrape_pages})...")
        if args.scrape_pages > 1:
            records = crawler.crawl_pagination(
                args.scrape, max_pages=args.scrape_pages, mode=args.scrape_mode
            )
            strategy = f"crawler ({args.scrape_pages} pages)"
        else:
            strategy, records = scraper.scrape(args.scrape, mode=args.scrape_mode)
        saved = exporter.save_csv(records, args.scrape_out, source_url=args.scrape)
        print(f"  ✓ Scraped {len(records)} records ({strategy}) -> {saved}")
        return

    if args.enhance_file:
        out_file = (
            args.output
            if args.output.lower().endswith(".mp4")
            else None
        )
        _run_enhance(
            input_path=args.enhance_file,
            output_path=out_file,
            scale=args.scale,
            tile_size=args.tile_size,
            use_gpu=not args.cpu,
            model_path=args.model,
        )
        return

    all_urls = list(args.urls) if args.urls else []
    if args.file and os.path.isfile(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                u = line.strip()
                if u and not u.startswith("#"):
                    all_urls.append(u)

    if not all_urls:
        parser.print_help()
        print("\n[!] Please specify at least one URL, -f <file>, or --enhance-file <video>.")
        sys.exit(1)

    print("============================================================")
    print(" AI Video Downloader & Enhancer Studio CLI")
    print(f" Total URLs     : {len(all_urls)}")
    print(f" Quality        : {args.quality}")
    print(f" Auto-Enhance   : {'Enabled (' + str(args.scale) + 'x)' if args.enhance else 'Disabled'}")
    print(f" Output folder  : {args.output}")
    print("============================================================")

    if len(all_urls) == 1:
        download_single(
            all_urls[0],
            args.quality,
            args.output,
            args.cookies,
            auto_enhance=args.enhance,
            scale=args.scale,
            tile_size=args.tile_size,
            use_gpu=not args.cpu,
            model_path=args.model,
        )
    else:
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            futures = [
                pool.submit(
                    download_single,
                    u,
                    args.quality,
                    args.output,
                    args.cookies,
                    args.enhance,
                    args.scale,
                    args.tile_size,
                    not args.cpu,
                    args.model,
                )
                for u in all_urls
            ]
            for f in futures:
                f.result()

    print("\n[✓] All tasks completed!")


if __name__ == "__main__":
    main()

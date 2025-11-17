"""Pattern analysis CLI commands for KrakenCLI.

Provides:
- pattern-scan: scan historical OHLC data for configured patterns and render
  results as table or JSON, with optional snapshot YAML export.
- pattern-heatmap: aggregate matches into time-bucket heatmaps.

Responsibilities:
- Keep orchestration in the analysis layer (PatternScanner).
- Present results with Rich tables and clean JSON output.
- Follow existing CLI dependency initialisation/wiring patterns.

Updates:
    v0.9.15 - 2025-11-16 - Added candlestick hammer and shooting star
        patterns in CLI.
    v0.9.14 - 2025-11-16 - Added MACD signal cross pattern support in CLI.
    v0.9.13 - 2025-11-16 - Initial pattern CLI scaffolding with scan and heatmap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

import click
from rich.console import Console
from rich.table import Table

from api.kraken_client import KrakenAPIClient
from analysis.pattern_scanner import (
    PatternHeatmap,
    PatternMatch,
    PatternScanner,
    PatternSnapshot,
    PatternStats,
)
from analysis.pattern_nl_mapper import (
    PatternDescriptionMapper,
    PatternMappingRequest,
)
from utils.helpers import format_percentage, format_timestamp


def register(
    cli_group: click.Group,
    *,
    console: Console,
    config: Any,
    call_with_retries: Callable[[Callable[[], Any], str, Optional[str]], Any],
) -> None:
    """Register pattern analysis commands on the provided Click group.

    This function attaches two commands:
    - pattern-scan
    - pattern-heatmap

    It also provides shared dependency helpers that store:
    - api_client: KrakenAPIClient
    - pattern_scanner: PatternScanner

    Args:
        cli_group: Root Click group to attach commands to.
        console: Rich console for formatted output.
        config: Application configuration object (Config).
        call_with_retries: Wrapper applying retry with progress to callables.
    """

    def _ensure_api_client(ctx: click.Context) -> Optional[KrakenAPIClient]:
        """Return a cached KrakenAPIClient or initialise a new one.

        Follows the same approach as other CLI modules: require configured
        credentials and store the client into ctx.obj.

        Args:
            ctx: Click context carrying shared objects.

        Returns:
            KrakenAPIClient instance or None when unavailable.
        """
        api_client = ctx.obj.get("api_client")
        if api_client is not None:
            return api_client

        if not config.has_credentials():
            console.print("[red]⚠️  API credentials not configured![/red]")
            console.print(
                "[yellow]Please configure your Kraken API credentials in .env "
                "file[/yellow]"
            )
            console.print("[yellow]See README.md for setup instructions[/yellow]")
            return None

        try:
            api_client = KrakenAPIClient(
                api_key=config.api_key,
                api_secret=config.api_secret,
                sandbox=config.sandbox,
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to initialize API client: {exc}[/red]")
            return None

        ctx.obj["api_client"] = api_client
        return api_client

    def _ensure_pattern_scanner(ctx: click.Context) -> Optional[PatternScanner]:
        """Return a cached PatternScanner initialised with the API client.

        The scanner uses logs/patterns as its cache directory. OHLC fetching
        is performed inside PatternScanner via KrakenAPIClient; the retries
        and progress UI are applied at the CLI call site where appropriate.

        Args:
            ctx: Click context carrying shared objects.

        Returns:
            PatternScanner instance or None when prerequisites are missing.
        """
        scanner: Optional[PatternScanner] = ctx.obj.get("pattern_scanner")
        if scanner is not None:
            return scanner

        api_client = _ensure_api_client(ctx)
        if api_client is None:
            return None

        try:
            scanner = PatternScanner(client=api_client, cache_dir=Path("logs/patterns"))
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to initialize pattern scanner: {exc}[/red]")
            return None

        ctx.obj["pattern_scanner"] = scanner
        return scanner

    def normalize_pair(pair: str) -> str:
        """Return normalized Kraken pair in upper-case."""
        return (pair or "").upper()

    def _parse_timeframe_minutes(value: str) -> int:
        """Parse timeframe label into minutes.

        Supported suffixes and examples:
        - m: minutes (e.g., '15m' -> 15)
        - h: hours (e.g., '1h' -> 60, '4h' -> 240)
        - d: days (e.g., '1d' -> 1440, '3d' -> 4320)

        Raises:
            click.BadParameter: When the label format is invalid.
        """
        raw = (value or "").strip().lower()
        if not raw:
            raise click.BadParameter("Timeframe is required.")
        try:
            if raw.endswith("m"):
                minutes = int(raw[:-1])
                if minutes < 1 or minutes > 10080:
                    raise ValueError
                return minutes
            if raw.endswith("h"):
                hours = int(raw[:-1])
                if hours < 1 or hours > 168:
                    raise ValueError
                return hours * 60
            if raw.endswith("d"):
                days = int(raw[:-1])
                if days < 1 or days > 7:
                    raise ValueError
                return days * 1440
        except ValueError:
            pass
        raise click.BadParameter(
            f"Invalid timeframe '{value}'. Use forms like 1m, 5m, 15m, 1h, 4h, 1d."
        )

    # ----------------------------------------------------------------------
    # pattern-scan
    # ----------------------------------------------------------------------
    @cli_group.command(name="pattern-scan")
    @click.option("--pair", "-p", required=True, help="Trading pair (e.g., ETHUSD)")
    @click.option(
        "--timeframe",
        "-t",
        required=True,
        help="Candle interval label (1m, 5m, 15m, 1h, 4h, 1d)",
    )
    @click.option(
        "--lookback",
        "-l",
        default=500,
        show_default=True,
        type=click.IntRange(50, 5000),
        help="Number of days to look back when fetching OHLC candles.",
    )
    @click.option(
        "--pattern",
        type=click.Choice(
            [
                "ma_crossover",
                "rsi_extreme",
                "bollinger_touch",
                "macd_signal_cross",
                "candle_hammer",
                "candle_shooting_star",
            ],
            case_sensitive=False,
        ),
        required=False,
        help="Pattern to scan for (mutually exclusive with --describe).",
    )
    @click.option(
        "--describe",
        "-d",
        type=str,
        required=False,
        help="Natural-language pattern description (mutually exclusive with --pattern).",
    )
    @click.option("--force-refresh", is_flag=True, help="Bypass cached results.")
    @click.option(
        "--export-snapshots",
        is_flag=True,
        help="Write detected snapshots to configs/backtests/ as YAML.",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Choice(["table", "json"], case_sensitive=False),
        default="table",
        show_default=True,
        help="Render output as a Rich table or JSON payload.",
    )
    @click.option(
        "--source",
        type=click.Choice(["api", "local"], case_sensitive=False),
        default="api",
        show_default=True,
        help="OHLC data source: Kraken API or local SQLite store.",
    )
    @click.option(
        "--db-path",
        type=click.Path(dir_okay=False, path_type=Path),
        default=Path("data/ohlc.db"),
        show_default=True,
        help="Path to local SQLite OHLC database (when --source=local).",
    )
    @click.pass_context
    def pattern_scan(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        lookback: int,
        pattern: Optional[str],
        describe: Optional[str],
        force_refresh: bool,
        export_snapshots: bool,
        output: str,
        source: str,
        db_path: Path,
    ) -> None:
        """Scan OHLC data for a specific pattern and render results.

        Displays a match table and a summary stats table or a JSON payload.
        Optionally exports detected snapshots to a YAML file suitable for
        backtests/config seeding.
        """
        scanner = _ensure_pattern_scanner(ctx)
        if scanner is None:
            return

        normalized_pair = normalize_pair(pair)
        try:
            timeframe_minutes = _parse_timeframe_minutes(timeframe)
        except click.BadParameter as exc:
            console.print(f"[red]❌ {exc}[/red]")
            raise click.Abort()

        # Determine pattern via explicit choice or NL description
        direction_filter: Optional[str] = None
        mapping_source: str = "explicit"
        mapping_confidence: Optional[float] = None
        mapping_notes: Optional[str] = None

        if (pattern and describe) or (not pattern and not describe):
            console.print(
                "[red]❌ Provide either --pattern or --describe (but not both).[/red]"
            )
            raise click.Abort()

        if describe:
            mapper = PatternDescriptionMapper()
            req = PatternMappingRequest(
                description=describe,
                pair=normalized_pair,
                timeframe_minutes=timeframe_minutes,
                lookback_days=lookback,
            )
            try:
                mapping = mapper.map(req)
            except ValueError as exc:
                console.print(f"[red]❌ Failed to map description: {exc}[/red]")
                raise click.Abort()

            pattern_name = mapping.pattern_name
            direction_filter = mapping.direction
            mapping_source = mapping.source
            mapping_confidence = mapping.confidence
            mapping_notes = mapping.notes
        else:
            pattern_name = (pattern or "").lower().strip()

        console.print(
            f"[bold blue]🔍 Scanning {normalized_pair} ({timeframe}) for "
            f"[cyan]{pattern_name}[/cyan]…[/bold blue]"
        )
        
        # Optional local source validation
        if source.lower() == "local":
            try:
                if not db_path.exists():
                    console.print(
                        f"[red]❌ Local OHLC DB not found at {db_path}[/red]"
                    )
                    console.print(
                        "[yellow]Run 'kraken_cli.py data ohlc-sync' to backfill, "
                        "or adjust --db-path[/yellow]"
                    )
                    raise click.Abort()
            except Exception:
                raise click.Abort()

        try:
            stats, matches, snapshots = call_with_retries(
                lambda: scanner.scan_pattern(
                    normalized_pair,
                    timeframe_minutes,
                    lookback,
                    pattern_name,
                    force_refresh=force_refresh,
                    data_source=source.lower(),
                    db_path=db_path if source.lower() == "local" else None,
                ),
                "Pattern scan",
                display_label="⏳ Scanning pattern",
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Pattern scan failed: {exc}[/red]")
            raise click.Abort()

        # Apply optional direction filter from NL mapping
        try:
            if direction_filter:
                matches = [m for m in matches if m.direction == direction_filter]
                # Recompute stats for filtered matches to keep summary consistent
                stats = scanner._compute_stats(
                    normalized_pair, timeframe_minutes, pattern_name, matches
                )
        except Exception:
            # Defensive: never let filtering break CLI
            pass

        if not matches:
            console.print(
                "[yellow]ℹ️  No matches found for the selected configuration.[/yellow]"
            )
            return

        if output.lower() == "json":
            payload = {
                "pair": normalized_pair,
                "timeframe": timeframe,
                "pattern": pattern_name,
                "lookback_candles_days": lookback,
                "stats": _stats_to_dict(stats),
                "matches": [_match_to_dict(m) for m in matches],
                "mapping": {
                    "source": mapping_source,
                    "direction": direction_filter,
                    "confidence": mapping_confidence,
                    "notes": mapping_notes,
                },
            }
            if export_snapshots:
                try:
                    yaml_path = scanner.export_snapshots_to_yaml(snapshots)
                    payload["snapshot_export"] = {
                        "count": len(snapshots),
                        "path": str(yaml_path),
                    }
                except Exception as exc:
                    payload["snapshot_export_error"] = str(exc)
            console.print(json.dumps(payload, indent=2))
            return

        # Table rendering
        match_table = Table(
            title=f"Pattern Matches — {pattern_name} on {normalized_pair} ({timeframe})",
            show_lines=False,
            expand=False,
        )
        match_table.add_column("Time (UTC)", style="cyan")
        match_table.add_column("Direction", style="yellow")
        match_table.add_column("Price", justify="right", style="magenta")
        match_table.add_column("Move %", justify="right", style="green")
        match_table.add_column("Window", justify="right", style="blue")
        match_table.add_column("Details", style="white")

        rows_to_show = matches[-100:] if len(matches) > 100 else matches
        for m in rows_to_show:
            details = f"{m.pattern_name}; win horizon={m.window}"
            match_table.add_row(
                format_timestamp(m.triggered_at, timezone="UTC"),
                m.direction,
                f"{m.close_price:,.6f}",
                format_percentage(m.move_pct, decimals=2),
                str(m.window),
                details,
            )

        console.print(match_table)

        summary_table = Table(
            title="Pattern Summary", show_lines=False, expand=False
        )
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")

        summary_table.add_row("Pattern", stats.pattern_name)
        summary_table.add_row("Pair", stats.pair)
        summary_table.add_row("Timeframe", timeframe)
        summary_table.add_row("Lookback (days)", str(lookback))
        if direction_filter:
            summary_table.add_row("Direction Filter", direction_filter)
        summary_table.add_row("Mapping Source", mapping_source)
        if mapping_confidence is not None:
            summary_table.add_row("Mapping Confidence", f"{mapping_confidence:.2f}")
        if mapping_notes:
            summary_table.add_row("Mapping Notes", mapping_notes)
        summary_table.add_row("Match Count", str(stats.total_matches))
        summary_table.add_row(
            "Avg Move %",
            format_percentage(stats.average_move_pct, decimals=2),
        )
        summary_table.add_row(
            "Median Move %",
            format_percentage(stats.median_move_pct, decimals=2),
        )
        summary_table.add_row(
            "Max Gain %",
            format_percentage(stats.max_move_pct, decimals=2),
        )
        summary_table.add_row(
            "Max Drawdown %",
            format_percentage(stats.min_move_pct, decimals=2),
        )

        console.print(summary_table)

        if export_snapshots:
            try:
                yaml_path = scanner.export_snapshots_to_yaml(snapshots)
                console.print(
                    f"[green]✅ Snapshots exported to "
                    f"[bold]{yaml_path}[/bold][/green]"
                )
            except Exception as exc:  # pragma: no cover - fs guard
                console.print(
                    f"[red]❌ Failed to export snapshots YAML: {exc}[/red]"
                )

    # ----------------------------------------------------------------------
    # pattern-heatmap
    # ----------------------------------------------------------------------
    @cli_group.command(name="pattern-heatmap")
    @click.option("--pair", "-p", required=True, help="Trading pair (e.g., ETHUSD)")
    @click.option(
        "--timeframe",
        "-t",
        required=True,
        help="Candle interval label (1m, 5m, 15m, 1h, 4h, 1d)",
    )
    @click.option(
        "--pattern",
        type=click.Choice(
            [
                "ma_crossover",
                "rsi_extreme",
                "bollinger_touch",
                "macd_signal_cross",
                "candle_hammer",
                "candle_shooting_star",
            ],
            case_sensitive=False
        ),
        required=True,
        help="Pattern to aggregate.",
    )
    @click.option(
        "--min-move",
        type=float,
        default=0.01,
        show_default=True,
        help="Minimum absolute move %% threshold to include in buckets.",
    )
    @click.option(
        "--window",
        type=click.IntRange(1, 50),
        default=PatternScanner.DEFAULT_MOVE_WINDOW,
        show_default=True,
        help="Future window used by detectors (informational).",
    )
    @click.option(
        "--group-by",
        type=click.Choice(["weekday", "hour", "weekday_hour"], case_sensitive=False),
        default="weekday",
        show_default=True,
        help="Aggregation bucket type.",
    )
    @click.option(
        "--lookback",
        "-l",
        default=500,
        show_default=True,
        type=click.IntRange(50, 5000),
        help="Number of days to look back when fetching OHLC candles.",
    )
    @click.option("--force-refresh", is_flag=True, help="Bypass cached results.")
    @click.option(
        "--output",
        "-o",
        type=click.Choice(["table", "json"], case_sensitive=False),
        default="table",
        show_default=True,
        help="Render output as a Rich table or JSON payload.",
    )
    @click.pass_context
    def pattern_heatmap(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        pattern: str,
        min_move: float,
        window: int,
        group_by: str,
        lookback: int,
        force_refresh: bool,
        output: str,
    ) -> None:
        """Aggregate pattern matches into time-based heatmap buckets."""
        scanner = _ensure_pattern_scanner(ctx)
        if scanner is None:
            return

        normalized_pair = normalize_pair(pair)
        try:
            timeframe_minutes = _parse_timeframe_minutes(timeframe)
        except click.BadParameter as exc:
            console.print(f"[red]❌ {exc}[/red]")
            raise click.Abort()

        pattern_name = pattern.lower().strip()
        console.print(
            f"[bold blue]🗺️  Building heatmap for {normalized_pair} "
            f"({timeframe}) — [cyan]{pattern_name}[/cyan][/bold blue]"
        )

        try:
            stats, matches, _snapshots = call_with_retries(
                lambda: scanner.scan_pattern(
                    normalized_pair,
                    timeframe_minutes,
                    lookback,
                    pattern_name,
                    force_refresh=force_refresh,
                ),
                "Pattern scan",
                display_label="⏳ Scanning pattern",
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Pattern scan failed: {exc}[/red]")
            raise click.Abort()

        # Filter by minimum absolute move percentage (units in %).
        filtered: list[PatternMatch] = [
            m for m in matches if abs(m.move_pct) >= float(min_move)
        ]
        if not filtered:
            console.print(
                "[yellow]ℹ️  No matches passed the threshold for heatmap "
                "construction. Consider lowering --min-move or increasing "
                "--lookback.[/yellow]"
            )
            return

        try:
            heatmap = scanner.build_heatmap(
                filtered,
                normalized_pair,
                timeframe_minutes,
                pattern_name,
                group_by=group_by.lower(),
            )
        except Exception as exc:
            console.print(f"[red]❌ Failed to build heatmap: {exc}[/red]")
            raise click.Abort()

        if not heatmap.buckets:
            console.print(
                "[yellow]ℹ️  Heatmap has no buckets. Try a wider lookback "
                "or different grouping.[/yellow]"
            )
            return

        if output.lower() == "json":
            payload = _heatmap_to_dict(heatmap)
            console.print(json.dumps(payload, indent=2))
            return

        # Table rendering for heatmap
        table = Table(
            title=(
                f"Pattern Heatmap — {pattern_name} on {normalized_pair} "
                f"({timeframe}) [{group_by}]"
            ),
            show_lines=False,
            expand=False,
        )
        table.add_column("Bucket", style="cyan")
        table.add_column("Matches", justify="right", style="yellow")
        table.add_column("Avg Move %", justify="right", style="green")

        # Sort buckets alphabetically for stable display
        for bucket_key in sorted(heatmap.buckets.keys()):
            bstats = heatmap.buckets[bucket_key]
            table.add_row(
                bucket_key,
                str(bstats.total_matches),
                format_percentage(bstats.average_move_pct, decimals=2),
            )

        console.print(table)

    # -----------------------------
    # Serialization helpers
    # -----------------------------
    def _match_to_dict(m: PatternMatch) -> dict[str, Any]:
        """Serialize PatternMatch to a JSON-friendly dict."""
        return {
            "pair": m.pair,
            "timeframe_minutes": int(m.timeframe),
            "pattern_name": m.pattern_name,
            "direction": m.direction,
            "triggered_at": m.triggered_at,
            "close_price": m.close_price,
            "move_pct": m.move_pct,
            "window": int(m.window),
        }

    def _stats_to_dict(s: PatternStats) -> dict[str, Any]:
        """Serialize PatternStats to a JSON-friendly dict."""
        return {
            "pair": s.pair,
            "timeframe_minutes": int(s.timeframe),
            "pattern_name": s.pattern_name,
            "total_matches": int(s.total_matches),
            "average_move_pct": s.average_move_pct,
            "median_move_pct": s.median_move_pct,
            "max_move_pct": s.max_move_pct,
            "min_move_pct": s.min_move_pct,
        }

    def _heatmap_to_dict(hm: PatternHeatmap) -> dict[str, Any]:
        """Serialize PatternHeatmap to a JSON-friendly dict."""
        return {
            "pair": hm.pair,
            "timeframe_minutes": int(hm.timeframe),
            "pattern_name": hm.pattern_name,
            "group_by": hm.group_by,
            "buckets": [
                {
                    "key": key,
                    "stats": _stats_to_dict(stats),
                }
                for key, stats in sorted(hm.buckets.items())
            ],
        }
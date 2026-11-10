"""Admin commands, grouped in the modules beside this one. Run from inside api/:

venv/bin/python -m app.cli set-role <nickname> admin
venv/bin/python -m app.cli set-role <nickname> user
venv/bin/python -m app.cli sync                 # new finished tournaments
venv/bin/python -m app.cli sync --watch 3600    # the same every hour (never more often)
venv/bin/python -m app.cli import-matches ../references/tournament_urls_limit.txt
venv/bin/python -m app.cli fetch-draft-links
venv/bin/python -m app.cli fetch-draft-actions
venv/bin/python -m app.cli fetch-draft-systems
venv/bin/python -m app.cli build-rosters
venv/bin/python -m app.cli import-catalog
venv/bin/python -m app.cli fetch-tournaments
venv/bin/python -m app.cli fetch-challonge
venv/bin/python -m app.cli set-challonge-name Smertik smertikk
venv/bin/python -m app.cli merge-players Raftal1k raftalia
venv/bin/python -m app.cli export-xlsx matches.xlsx
venv/bin/python -m app.cli check-matches
venv/bin/python -m app.cli list-tournaments
venv/bin/python -m app.cli set-player-name "Anemo main" Northwar
venv/bin/python -m app.cli set-tournament-winner "Abyss Weekend 16" rpyt02 --source challonge.com/hoth_fast_16
venv/bin/python -m app.cli delete-tournaments --first 2
venv/bin/python -m app.cli add-challonge-tournament https://challonge.com/afc_fast_5 "Abyss Fight Club: Abyss Weekend 5"
venv/bin/python -m app.cli set-challonge-url "HotH: Abyss Weekend 6" https://challonge.com/hoth_fast_6
venv/bin/python -m app.cli check-challonge
venv/bin/python -m app.cli set-tournament-event "Abyss Fight Club 4" challonge-afc_4_1="Group stage 1" \
    challonge-afc_4_3="Main Stage"
venv/bin/python -m app.cli export-telegram @abysscup --photos
venv/bin/python -m app.cli telegram-photos @abysscup      # only the results posts' photos (after export-telegram)
venv/bin/python -m app.cli telegram-ocr @abysscup         # their text, read on this Mac
venv/bin/python -m app.cli add-manual-games brackets/abyss_cup_major_1_games.json
venv/bin/python -m app.cli export-aspirine abysscup_minor_24 abysscup_minor_s2 abysscup_major
venv/bin/python -m app.cli import-aspirine
venv/bin/python -m app.cli poll-stream
"""

import argparse

from ..models import Role
from .archives import (
    add_manual_games,
    export_aspirine,
    export_telegram,
    import_aspirine,
    telegram_ocr,
    telegram_photos,
)
from .fetch import (
    fetch_actions,
    fetch_links,
    fetch_systems,
    fetch_tournaments,
    import_hoth_hub,
    import_matches,
    import_names,
    rebuild_rosters,
    refresh_times,
    run_fetch_abyss,
    run_fetch_challonge,
    run_sync,
    run_worker,
)
from .players import (
    add_player,
    merge_players,
    set_challonge_name,
    set_player_name,
)
from .site import (
    import_article,
    poll_stream,
    set_news_translation,
    set_role,
)
from .tournaments import (
    add_challonge_tournament,
    add_manual_tournament,
    check_challonge,
    check_matches,
    export_matches,
    remove_tournaments,
    set_challonge_url,
    set_match_winner,
    set_organizer,
    set_tournament_event,
    set_tournament_winner,
    show_tournaments,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    role_cmd = commands.add_parser("set-role", help="Make a user an admin or a regular user")
    role_cmd.add_argument("nickname")
    role_cmd.add_argument("role", choices=[role.value for role in Role])
    import_cmd = commands.add_parser("import-matches", help="Import finished matches from the tournament site")
    import_cmd.add_argument("urls_file", nargs="?", help="Text file with one matches API URL per line")
    import_cmd.add_argument(
        "--json", nargs="+", default=[], metavar="FILE", help="Import saved API responses instead of downloading"
    )
    links_cmd = commands.add_parser("fetch-draft-links", help="Fetch the spectator link of every imported draft")
    links_cmd.add_argument("--refresh", action="store_true", help="Fetch again for matches that already have links")
    actions_cmd = commands.add_parser(
        "fetch-draft-actions", help="Fetch every draft's bans and picks over its socket (after fetch-draft-links)"
    )
    actions_cmd.add_argument("--refresh", action="store_true", help="Fetch again for drafts already stored")
    times_cmd = commands.add_parser(
        "refresh-times",
        help="Read again the stored games whose times changed on the site (sync does it for recent ones)",
    )
    times_cmd.add_argument("tournaments", nargs="*", help="Tournament ids; every stored tournament without any")
    commands.add_parser("import-catalog", help="Import the site's character and weapon names")
    commands.add_parser("fetch-tournaments", help="Fetch tournament organizers, prizes and finish dates")
    challonge_cmd = commands.add_parser(
        "fetch-challonge", help="Fetch finished tournaments' Challonge brackets (after fetch-tournaments)"
    )
    challonge_cmd.add_argument("--refetch", action="store_true", help="Fetch brackets already stored again")
    commands.add_parser("build-rosters", help="Rebuild every player's roster per tournament from the drafts")
    commands.add_parser("fetch-draft-systems", help="Fetch the draft systems' rules and cost tables")
    sync_cmd = commands.add_parser("sync", help="Import new finished tournaments with their drafts")
    sync_cmd.add_argument(
        "--watch", type=int, metavar="SECONDS", help="Repeat every SECONDS (at least 3600) until stopped"
    )
    commands.add_parser("worker", help="Run the background sync, live poll and stream as a process of their own")
    export_cmd = commands.add_parser("export-xlsx", help="Export imported matches to an Excel workbook")
    export_cmd.add_argument("path", nargs="?", default="matches.xlsx")
    check_cmd = commands.add_parser("check-matches", help="List suspicious data in the imported matches")
    check_cmd.add_argument("--examples", type=int, default=5, help="Examples to print per kind")
    commands.add_parser("list-tournaments", help="List imported tournaments, oldest first")
    delete_cmd = commands.add_parser("delete-tournaments", help="Delete tournaments and everything in them")
    delete_cmd.add_argument("ids", nargs="*", help="Tournament ids from list-tournaments")
    delete_cmd.add_argument("--first", type=int, help="Delete the N oldest tournaments (by first match)")
    delete_cmd.add_argument("--yes", action="store_true", help="Don't ask for confirmation")
    name_cmd = commands.add_parser("set-player-name", help="Show a tournament player under a nickname of your choice")
    name_cmd.add_argument("player", help="Site user id or any nickname they played under")
    name_cmd.add_argument("name", nargs="?", help="Nickname to show")
    name_cmd.add_argument("--clear", action="store_true", help="Go back to the nickname from their latest game")
    merge_cmd = commands.add_parser(
        "merge-players", help="Count one site account as another (one person, two accounts)"
    )
    merge_cmd.add_argument("player", help="Account to merge away: site user id or any nickname it played under")
    merge_cmd.add_argument("into", nargs="?", help="Account it counts as")
    merge_cmd.add_argument("--clear", action="store_true", help="Undo the merge")
    alias_cmd = commands.add_parser("set-challonge-name", help="Tie a Challonge name to a player it doesn't match")
    alias_cmd.add_argument("name", help="The name on Challonge")
    alias_cmd.add_argument("player", nargs="?", help="Site user id or any nickname they played under")
    alias_cmd.add_argument("--clear", action="store_true", help="Untie the name")
    winner_cmd = commands.add_parser(
        "set-tournament-winner", help="Set a tournament's winner when its final has no result"
    )
    winner_cmd.add_argument("tournament", help="Tournament id or exact title")
    winner_cmd.add_argument("player", nargs="?", help="Site user id or nickname of the winner")
    winner_cmd.add_argument("--source", help="Where the result comes from, e.g. a Challonge page")
    winner_cmd.add_argument("--clear", action="store_true", help="Remove the winner set by hand")
    match_winner_cmd = commands.add_parser(
        "set-match-winner", help="Set a match's winner when its stored games say otherwise"
    )
    match_winner_cmd.add_argument("match", help="Match id (from its page's address)")
    match_winner_cmd.add_argument("player", nargs="?", help="Site user id or nickname of the winner")
    match_winner_cmd.add_argument("--source", help="Where the result comes from")
    match_winner_cmd.add_argument("--clear", action="store_true", help="Remove the winner set by hand")
    add_ch_cmd = commands.add_parser(
        "add-challonge-tournament", help="Add a tournament played only on Challonge, with its bracket"
    )
    add_ch_cmd.add_argument("url", help="The Challonge bracket, e.g. https://challonge.com/afc_fast_5")
    add_ch_cmd.add_argument("title", help="The title to show")
    add_ch_cmd.add_argument("--organizer", help="Organizer's name as on the site's tournaments, e.g. 'Astro Liber'")
    add_ch_cmd.add_argument("--date", help="When it was played (YYYY-MM-DD); estimated from the bracket if left out")
    add_ch_cmd.add_argument("--ended", help="Its last day (YYYY-MM-DD) when played over several; needs --date")
    add_ch_cmd.add_argument(
        "--page", help="The bracket from a file instead of Challonge: its saved page (HTML) or TournamentStore JSON"
    )
    add_ch_cmd.add_argument("--team", action="store_true", help="A team event: left out of personal statistics")
    add_ch_cmd.add_argument("--major", action="store_true", help="Count it as a major tournament")
    url_cmd = commands.add_parser("set-challonge-url", help="Link a site tournament to its Challonge bracket")
    url_cmd.add_argument("tournament", help="Tournament id or exact title")
    url_cmd.add_argument("url", nargs="?", help="The Challonge bracket")
    url_cmd.add_argument("--clear", action="store_true", help="Remove the link and the stored bracket")
    commands.add_parser("check-challonge", help="List where Challonge brackets and the site's matches disagree")
    commands.add_parser("import-hoth-hub", help="Write House of the Hearth's match timers from HotH Hub into the site")
    abyss_cmd = commands.add_parser("fetch-abyss", help="Import Spiral Abyss phases (floor 12) from alioth.wiki")
    abyss_cmd.add_argument("--refetch", action="store_true", help="Fetch every phase again")
    player_cmd = commands.add_parser("add-player", help="Add a person who played only in bracket-only tournaments")
    player_cmd.add_argument("name", help="The name to show")
    player_cmd.add_argument("challonge_names", nargs="*", help="Their names in brackets, tied to them")
    tg_cmd = commands.add_parser("export-telegram", help="Save a Telegram channel's history as JSON (logs in as you)")
    tg_cmd.add_argument("channel", help="The channel, e.g. @abysscup")
    tg_cmd.add_argument("--photos", action="store_true", help="Download the posts' photos too")
    asp_cmd = commands.add_parser(
        "export-aspirine", help="Save old tournaments' games and drafts from draft.aspirine.su"
    )
    asp_cmd.add_argument("slugs", nargs="+", help="Tournament slugs: draft.aspirine.su/tournament/<slug>/")
    trn_cmd = commands.add_parser("set-news-translation", help="Attach a translated .docx to a news post")
    trn_cmd.add_argument("news_id", type=int)
    trn_cmd.add_argument("file", help="The translated document (.docx)")
    trn_cmd.add_argument("--title", help="Its title; else the document's first heading or line")
    art_cmd = commands.add_parser("import-article", help="Import a .docx as a draft article, for an admin to approve")
    art_cmd.add_argument("file", help="The document (.docx)")
    art_cmd.add_argument("--by", required=True, help="Nickname of the member it's imported under")
    art_cmd.add_argument("--title", help="Its title; else the document's first heading or line")
    art_cmd.add_argument("--author", help="Its author as shown; else the member")
    commands.add_parser("poll-stream", help="Read the streams' Telegram channels and Twitch status once")
    commands.add_parser("import-aspirine", help="Store the old tournaments export-aspirine saved as matches")
    games_cmd = commands.add_parser("add-manual-games", help="Store games of hand-entered tournaments from a JSON file")
    games_cmd.add_argument("file", help="JSON: matches with tournament, date, players, games (rooms, penalty), winner")
    tgp_cmd = commands.add_parser("telegram-photos", help="Download the photos of an exported channel's results posts")
    tgp_cmd.add_argument("channel", help="The channel, e.g. @abysscup (export-telegram it first)")
    tgp_cmd.add_argument("--posts", help="Only posts whose text matches this regular expression instead")
    tgp_cmd.add_argument("--since", help="Only posts from this date on (YYYY-MM-DD); with dates, every post's photo")
    tgp_cmd.add_argument("--until", help="Only posts up to this date (YYYY-MM-DD)")
    tgo_cmd = commands.add_parser("telegram-ocr", help="Read the text on a channel's downloaded photos (macOS)")
    tgo_cmd.add_argument("channel", help="The channel, e.g. @abysscup")
    org_cmd = commands.add_parser("set-organizer", help="Show an organizer under another name, or as another organizer")
    org_cmd.add_argument("organizer", help="The organizer's name on the site or their id")
    org_cmd.add_argument("--name", help="The name to show, e.g. 'House of the Hearth'")
    org_cmd.add_argument("--into", help="Another organizer this one counts as (one series, two accounts)")
    org_cmd.add_argument("--clear", action="store_true", help="Show them as on the site again")
    manual_cmd = commands.add_parser(
        "add-manual-tournament", help="Add a tournament from a bracket entered by hand (a JSON file)"
    )
    manual_cmd.add_argument("file", help="JSON: slug, title, started, ended, rounds, third_place, major, organizer")
    event_cmd = commands.add_parser("set-tournament-event", help="Group tournaments as the stages of one event")
    event_cmd.add_argument("event", nargs="?", help="The event's name, e.g. 'Abyss Fight Club 4'")
    event_cmd.add_argument(
        "stages", nargs="+", help="Tournament ids or exact titles in stage order; 'title=Stage name' names a stage"
    )
    event_cmd.add_argument("--clear", action="store_true", help="Take the tournaments out of their event")
    args = parser.parse_args()
    if args.command == "set-role":
        set_role(args.nickname, Role(args.role))
    elif args.command == "import-matches":
        if not args.urls_file and not args.json:
            parser.error("import-matches needs a URLs file or --json files")
        import_matches(args.urls_file, args.json)
    elif args.command == "fetch-draft-links":
        fetch_links(args.refresh)
    elif args.command == "fetch-draft-actions":
        fetch_actions(args.refresh)
    elif args.command == "sync":
        run_sync(args.watch)
    elif args.command == "worker":
        run_worker()
    elif args.command == "fetch-draft-systems":
        fetch_systems()
    elif args.command == "build-rosters":
        rebuild_rosters()
    elif args.command == "fetch-tournaments":
        fetch_tournaments()
    elif args.command == "fetch-challonge":
        run_fetch_challonge(args.refetch)
    elif args.command == "import-catalog":
        import_names()
    elif args.command == "export-xlsx":
        export_matches(args.path)
    elif args.command == "check-matches":
        check_matches(args.examples)
    elif args.command == "list-tournaments":
        show_tournaments()
    elif args.command == "set-player-name":
        if not args.clear and not args.name:
            parser.error("set-player-name needs a name or --clear")
        set_player_name(args.player, None if args.clear else args.name)
    elif args.command == "merge-players":
        if not args.clear and not args.into:
            parser.error("merge-players needs the account to merge into, or --clear")
        merge_players(args.player, None if args.clear else args.into)
    elif args.command == "set-challonge-name":
        if not args.clear and not args.player:
            parser.error("set-challonge-name needs a player or --clear")
        set_challonge_name(args.name, None if args.clear else args.player)
    elif args.command == "set-tournament-winner":
        if not args.clear and not args.player:
            parser.error("set-tournament-winner needs a player or --clear")
        set_tournament_winner(args.tournament, None if args.clear else args.player, args.source)
    elif args.command == "set-match-winner":
        if not args.clear and not args.player:
            parser.error("set-match-winner needs a player or --clear")
        set_match_winner(args.match, None if args.clear else args.player, args.source)
    elif args.command == "add-challonge-tournament":
        add_challonge_tournament(
            args.url, args.title, args.organizer, args.date, args.ended, args.team, args.major, args.page
        )
    elif args.command == "set-challonge-url":
        if not args.clear and not args.url:
            parser.error("set-challonge-url needs a URL or --clear")
        set_challonge_url(args.tournament, None if args.clear else args.url)
    elif args.command == "set-tournament-event":
        if args.clear:
            set_tournament_event(None, ([args.event] if args.event else []) + args.stages)
        else:
            set_tournament_event(args.event, args.stages)
    elif args.command == "add-manual-tournament":
        add_manual_tournament(args.file)
    elif args.command == "set-organizer":
        if not (args.clear or args.name or args.into):
            parser.error("set-organizer needs --name, --into or --clear")
        set_organizer(args.organizer, args.name, args.into, args.clear)
    elif args.command == "add-player":
        add_player(args.name, args.challonge_names)
    elif args.command == "export-telegram":
        export_telegram(args.channel, args.photos)
    elif args.command == "export-aspirine":
        export_aspirine(args.slugs)
    elif args.command == "set-news-translation":
        set_news_translation(args.news_id, args.file, args.title)
    elif args.command == "import-article":
        import_article(args.file, args.by, args.title, args.author)
    elif args.command == "poll-stream":
        poll_stream()
    elif args.command == "import-aspirine":
        import_aspirine()
    elif args.command == "add-manual-games":
        add_manual_games(args.file)
    elif args.command == "telegram-photos":
        telegram_photos(args.channel, args.posts, args.since, args.until)
    elif args.command == "telegram-ocr":
        telegram_ocr(args.channel)
    elif args.command == "fetch-abyss":
        run_fetch_abyss(args.refetch)
    elif args.command == "import-hoth-hub":
        import_hoth_hub()
    elif args.command == "check-challonge":
        check_challonge()
    elif args.command == "refresh-times":
        refresh_times(args.tournaments)
    elif args.command == "delete-tournaments":
        if not args.ids and not args.first:
            parser.error("delete-tournaments needs tournament ids or --first N")
        remove_tournaments(args.ids, args.first, args.yes)

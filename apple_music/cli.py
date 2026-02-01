"""CLI for Apple Music assistant using core.cli_framework."""

from __future__ import annotations

import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.cli_framework import CLIApp

from .client import AppleMusicClient, AppleMusicError
from .config import DEFAULT_PROFILE, load_profile

# Artist name constants (to avoid duplicate literals)
_ARTIST_GIPSY_KINGS = "Gipsy Kings"
_ARTIST_JUAN_LUIS_GUERRA = "Juan Luis Guerra"
_ARTIST_ALIZEE = "Alizée"
_ARTIST_MYLENE_FARMER = "Mylène Farmer"
_ARTIST_GREAT_BIG_SEA = "Great Big Sea"
_ARTIST_STAN_ROGERS = "Stan Rogers"
_ARTIST_THE_LONGEST_JOHNS = "The Longest Johns"
_ARTIST_LIMP_BIZKIT = "Limp Bizkit"
_ARTIST_LINKIN_PARK = "Linkin Park"
_ARTIST_RAGE_AGAINST_THE_MACHINE = "Rage Against the Machine"
_ARTIST_SYSTEM_OF_A_DOWN = "System Of A Down"
_ARTIST_SMASHING_PUMPKINS = "Smashing Pumpkins"
_ARTIST_KNIFE_PARTY = "Knife Party"

# Create the CLI app
app = CLIApp(
    "apple-music-assistant",
    "Apple Music assistant CLI for playlist management.",
    add_common_args=True,
)


@dataclass
class PlaylistCreationConfig:
    """Configuration for creating a playlist from seed tracks."""

    name: str
    description: str | None = None
    count: int = 20
    shuffle_seed: int | None = None
    storefront: str | None = None
    dry_run: bool = False


# Playlist presets for the create command
PRESETS = {
    "spanish": {
        "name": "Spanish Vibes",
        "description": None,
        "seeds": [
            ("Bamboleo", _ARTIST_GIPSY_KINGS),
            ("Volare", _ARTIST_GIPSY_KINGS),
            ("Djobi Djoba", _ARTIST_GIPSY_KINGS),
            ("Baila Me", _ARTIST_GIPSY_KINGS),
            ("La Dona", _ARTIST_GIPSY_KINGS),
            ("Bem, Bem, Maria", _ARTIST_GIPSY_KINGS),
            ("Oye Como Va", "Santana"),
            ("Corazón Espinado", "Santana Maná"),
            ("Maria Maria", "Santana"),
            ("La Camisa Negra", "Juanes"),
            ("Bailando", "Enrique Iglesias"),
            ("Mi Gente", "J Balvin"),
            ("Despacito", "Luis Fonsi"),
            ("Danza Kuduro", "Don Omar"),
            ("Suavemente", "Elvis Crespo"),
            ("La Vida Es Un Carnaval", "Celia Cruz"),
            ("Vivir Mi Vida", "Marc Anthony"),
            ("La Tortura", "Shakira Alejandro Sanz"),
            ("Waka Waka (Esto Es África)", "Shakira"),
            ("Hips Don't Lie", "Shakira Wyclef Jean"),
            ("Rayando el Sol", "Maná"),
            ("Obsesión", "Aventura"),
            ("La Bicicleta", "Carlos Vives Shakira"),
            ("Propuesta Indecente", "Romeo Santos"),
            ("Gasolina", "Daddy Yankee"),
            ("Bachata en Fukuoka", _ARTIST_JUAN_LUIS_GUERRA),
            ("Burbujas de Amor", _ARTIST_JUAN_LUIS_GUERRA),
            ("Eres", "Café Tacvba"),
            ("La Flaca", "Jarabe de Palo"),
            ("Corazón Partío", "Alejandro Sanz"),
            ("La Vida Es un Carnaval", "Celia Cruz"),
            ("Burbujas de Amor", _ARTIST_JUAN_LUIS_GUERRA),
            ("Me Gustas Tu", "Manu Chao"),
            ("La Cintura", "Alvaro Soler"),
            ("Sofia", "Alvaro Soler"),
            ("Borro Cassette", "Maluma"),
            ("Beso en la Boca", "Aventura"),
            ("Bailar", "Elvis Crespo"),
        ],
    },
    "sonic": {
        "name": "Sonic Movie Hits",
        "description": "Popular songs featured in the Sonic movies",
        "seeds": [
            ("Speed Me Up", "Wiz Khalifa Ty Dolla Sign Lil Yachty Sueco the Child"),
            ("Stars In The Sky", "Kid Cudi"),
            ("Don't Stop Me Now", "Queen"),
            ("It's Tricky", "RUN DMC"),
            ("Where Evil Grows", "Poppy Family"),
            ("Green Hill Zone", "Sonic the Hedgehog"),
            ("Friends", "Hyper Potions"),
            ("Bamboleo", _ARTIST_GIPSY_KINGS),
            ("Uptown Funk", "Mark Ronson Bruno Mars"),
            ("Barracuda", "Heart"),
            ("Thunderstruck", "AC/DC"),
        ],
    },
    "coldplay": {
        "name": "Coldplay Greatest Hits",
        "description": "Coldplay essentials",
        "seeds": [
            ("Yellow", "Coldplay"),
            ("Clocks", "Coldplay"),
            ("Viva La Vida", "Coldplay"),
            ("Fix You", "Coldplay"),
            ("The Scientist", "Coldplay"),
            ("Paradise", "Coldplay"),
            ("Adventure of a Lifetime", "Coldplay"),
            ("Hymn for the Weekend", "Coldplay"),
            ("Something Just Like This", "Coldplay The Chainsmokers"),
            ("A Sky Full of Stars", "Coldplay"),
            ("Speed of Sound", "Coldplay"),
            ("In My Place", "Coldplay"),
            ("Magic", "Coldplay"),
            ("Higher Power", "Coldplay"),
            ("Everglow", "Coldplay"),
            ("Talk", "Coldplay"),
            ("Violet Hill", "Coldplay"),
            ("Orphans", "Coldplay"),
            ("My Universe", "Coldplay BTS"),
            ("Shiver", "Coldplay"),
        ],
    },
    "french-pop": {
        "name": "French Pop Vibes",
        "description": "French pop hits and classics",
        "seeds": [
            ("Moi... Lolita", _ARTIST_ALIZEE),
            ("J'en ai marre!", _ARTIST_ALIZEE),
            ("Gourmandises", _ARTIST_ALIZEE),
            ("Parler tout bas", _ARTIST_ALIZEE),
            ("A contre-courant", _ARTIST_ALIZEE),
            ("Mademoiselle Juliette", _ARTIST_ALIZEE),
            ("Les Collines (Never Leave You)", _ARTIST_ALIZEE),
            ("Désenchantée", _ARTIST_MYLENE_FARMER),
            ("Sans contrefaçon", _ARTIST_MYLENE_FARMER),
            ("Libertine", _ARTIST_MYLENE_FARMER),
            ("Pourvu qu'elles soient douces", _ARTIST_MYLENE_FARMER),
            ("Sans logique", _ARTIST_MYLENE_FARMER),
            ("California", _ARTIST_MYLENE_FARMER),
            ("L'Âme-Stram-Gram", _ARTIST_MYLENE_FARMER),
            ("Stolen Car", _ARTIST_MYLENE_FARMER + " Sting"),
            ("Papaoutai", "Stromae"),
            ("Alors on danse", "Stromae"),
            ("Formidable", "Stromae"),
            ("Balance Ton Quoi", "Angèle"),
            ("Bruxelles je t'aime", "Angèle"),
            ("Christine", "Christine and the Queens"),
            ("Tourner Dans Le Vide", "Indila"),
            ("Dernière danse", "Indila"),
            ("Je veux", "Zaz"),
            ("La Grenade", "Clara Luciani"),
            ("Djadja", "Aya Nakamura"),
            ("Makeba", "Jain"),
            ("Joe le taxi", "Vanessa Paradis"),
            ("Je vole", "Louane"),
            ("Comme des enfants", "Cœur de Pirate"),
            ("Week-end à Rome", "Etienne Daho"),
            ("Ella, elle l'a", "France Gall"),
            ("Voyage voyage", "Desireless"),
            ("Les Champs-Élysées", "Joe Dassin"),
            ("J't'emmène au vent", "Louise Attaque"),
            ("Je te promets", "Johnny Hallyday"),
            ("Elle me dit", "Mika"),
            ("Moi aimer toi", "Vianney"),
            ("Le Dernier Jour du Disco", "Juliette Armanet"),
            ("Je sais pas danser", "Pomme"),
            ("Lisztomania", "Phoenix"),
            ("Get Lucky", "Daft Punk Pharrell Williams"),
            ("Sexy Boy", "Air"),
            ("Midnight City", "M83"),
            ("Complètement fou", "Yelle"),
            ("Un autre que moi", "Fishbach"),
        ],
    },
    "canadian-shanty": {
        "name": "Canadian Shanty Vibes",
        "description": "Sea shanty and folk-leaning Canadian anthems",
        "seeds": [
            ("Ordinary Day", _ARTIST_GREAT_BIG_SEA),
            ("Sea Of No Cares", _ARTIST_GREAT_BIG_SEA),
            ("When I'm Up", _ARTIST_GREAT_BIG_SEA),
            ("Consequence Free", _ARTIST_GREAT_BIG_SEA),
            ("The Night Pat Murphy Died", _ARTIST_GREAT_BIG_SEA),
            ("General Taylor", _ARTIST_GREAT_BIG_SEA),
            ("Mari-Mac", _ARTIST_GREAT_BIG_SEA),
            ("Lukey", _ARTIST_GREAT_BIG_SEA),
            ("Captain Kidd", _ARTIST_GREAT_BIG_SEA),
            ("Ferryland Sealer", _ARTIST_GREAT_BIG_SEA),
            ("Barrett's Privateers", _ARTIST_STAN_ROGERS),
            ("Northwest Passage", _ARTIST_STAN_ROGERS),
            ("The Mary Ellen Carter", _ARTIST_STAN_ROGERS),
            ("Forty-Five Years", _ARTIST_STAN_ROGERS),
            ("The Log Driver's Waltz", "Kate and Anna McGarrigle"),
            ("The Islander", "Dave Gunning"),
            ("Lighthouse", "The Waifs"),
            ("The Last Saskatchewan Pirate", "The Arrogant Worms"),
            ("Northwest Passage", _ARTIST_THE_LONGEST_JOHNS),
            ("Leave Her Johnny", _ARTIST_THE_LONGEST_JOHNS),
            ("Wellerman", _ARTIST_THE_LONGEST_JOHNS),
            ("Home For A Rest", "Spirit of the West"),
            ("The Irish Rover", "The Irish Rovers"),
            ("Drunken Sailor", "The Irish Rovers"),
            ("Farewell to Nova Scotia", "The Irish Descendants"),
            ("Son of a Sailor", "Jimmy Buffett"),
            ("The Sailor's Prayer", "Tom Lewis"),
            ("The Grey Funnel Line", "Cyril Tawney"),
        ],
    },
    "angry-90s-rock": {
        "name": "Angry 90s Rock",
        "description": "Heavy alt/nu-metal anthems from the 90s/early 00s",
        "seeds": [
            ("Break Stuff", _ARTIST_LIMP_BIZKIT),
            ("Nookie", _ARTIST_LIMP_BIZKIT),
            ("Rollin'", _ARTIST_LIMP_BIZKIT),
            ("Last Resort", "Papa Roach"),
            ("Between Angels and Insects", "Papa Roach"),
            ("One Step Closer", _ARTIST_LINKIN_PARK),
            ("Papercut", _ARTIST_LINKIN_PARK),
            ("Crawling", _ARTIST_LINKIN_PARK),
            ("Freak on a Leash", "Korn"),
            ("Got the Life", "Korn"),
            ("Falling Away from Me", "Korn"),
            ("Killing in the Name", _ARTIST_RAGE_AGAINST_THE_MACHINE),
            ("Bulls on Parade", _ARTIST_RAGE_AGAINST_THE_MACHINE),
            ("Guerrilla Radio", _ARTIST_RAGE_AGAINST_THE_MACHINE),
            ("Testify", _ARTIST_RAGE_AGAINST_THE_MACHINE),
            ("Chop Suey!", _ARTIST_SYSTEM_OF_A_DOWN),
            ("B.Y.O.B.", _ARTIST_SYSTEM_OF_A_DOWN),
            ("Toxicity", _ARTIST_SYSTEM_OF_A_DOWN),
            ("Sugar", _ARTIST_SYSTEM_OF_A_DOWN),
            ("Wait and Bleed", "Slipknot"),
            ("Duality", "Slipknot"),
            ("My Own Summer (Shove It)", "Deftones"),
            ("Change (In the House of Flies)", "Deftones"),
            ("March of the Pigs", "Nine Inch Nails"),
            ("Head Like a Hole", "Nine Inch Nails"),
            ("The Beautiful People", "Marilyn Manson"),
            ("Stinkfist", "TOOL"),
            ("Down with the Sickness", "Disturbed"),
            ("Stupify", "Disturbed"),
            ("Bodies", "Drowning Pool"),
            ("Dragula", "Rob Zombie"),
            ("Whatever", "Godsmack"),
            ("Awake", "Godsmack"),
            ("Walk", "Pantera"),
            ("Cowboys From Hell", "Pantera"),
            ("Push It", "Static-X"),
            ("Deny", "Sevendust"),
            ("Dig", "Mudvayne"),
            ("When Worlds Collide", "Powerman 5000"),
            ("Loco", "Coal Chamber"),
            ("Click Click Boom", "Saliva"),
            ("Boom", "P.O.D."),
            ("Alive", "P.O.D."),
            ("Bullet with Butterfly Wings", _ARTIST_SMASHING_PUMPKINS),
            ("Zero", _ARTIST_SMASHING_PUMPKINS),
            ("Bodies", _ARTIST_SMASHING_PUMPKINS),
            ("Unsung", "Helmet"),
            ("Davidian", "Machine Head"),
            ("Edgecrusher", "Fear Factory"),
            ("Man in the Box", "Alice In Chains"),
            ("Rusty Cage", "Soundgarden"),
        ],
    },
    "dubstep": {
        "name": "Epic Dubstep",
        "description": "Iconic bass-heavy dubstep drops",
        "seeds": [
            ("Scary Monsters and Nice Sprites", "Skrillex"),
            ("Bangarang", "Skrillex"),
            ("First of the Year (Equinox)", "Skrillex"),
            ("Kill EVERYBODY", "Skrillex"),
            ("Cinema (Skrillex Remix)", "Benny Benassi Skrillex"),
            ("Ruffneck (Full Flex)", "Skrillex"),
            ("Bass Cannon", "Flux Pavilion"),
            ("I Can't Stop", "Flux Pavilion"),
            ("Gold Dust (Flux Pavilion Remix)", "DJ Fresh"),
            ("Sweet Shop", "Doctor P"),
            ("Big Boss", "Doctor P"),
            ("Promises", "Nero"),
            ("Innocence", "Nero"),
            ("Me and You", "Nero"),
            ("Doomsday", "Nero"),
            ("Eyes on Fire (Zeds Dead Remix)", "Blue Foundation"),
            ("Adrenaline", "Zeds Dead"),
            ("Centipede", _ARTIST_KNIFE_PARTY),
            ("Internet Friends", _ARTIST_KNIFE_PARTY),
            ("Bonfire", _ARTIST_KNIFE_PARTY),
            ("Swagga", "Datsik Excision"),
            ("Woo Boost", "Rusko"),
            ("Night", "Benga Coki"),
            ("Midnight Request Line", "Skream"),
            ("Tidal Wave", "Sub Focus"),
            ("Rock It", "Sub Focus"),
            ("Crave You (Adventure Club Remix)", "Flight Facilities"),
            ("Sierra Leone", "Mt Eden"),
            ("Push It", "Zeds Dead"),
        ],
    },
}


def _resolve_tokens(args) -> tuple[str | None, str | None]:
    """Resolve developer and user tokens from args, env, or config."""
    profile = getattr(args, "profile", None) or DEFAULT_PROFILE
    config_path = getattr(args, "config", None)
    _, profile_cfg = load_profile(profile, config_path)
    developer_token = (
        getattr(args, "developer_token", None)
        or os.environ.get("APPLE_MUSIC_DEVELOPER_TOKEN")
        or profile_cfg.get("developer_token")
    )
    user_token = (
        getattr(args, "user_token", None)
        or os.environ.get("APPLE_MUSIC_USER_TOKEN")
        or profile_cfg.get("user_token")
    )
    return developer_token, user_token


def _get_client(args) -> AppleMusicClient:
    """Create an AppleMusicClient from args."""
    developer_token, user_token = _resolve_tokens(args)
    if not developer_token:
        print("Missing developer token. Provide --developer-token or set developer_token in credentials.ini.", file=sys.stderr)
        raise SystemExit(2)
    if not user_token:
        print("Missing user token. Provide --user-token or set user_token in credentials.ini.", file=sys.stderr)
        raise SystemExit(2)
    return AppleMusicClient(developer_token, user_token)


def _output_json(args, payload: dict) -> int:
    """Output JSON payload to stdout or file."""
    pretty = getattr(args, "pretty", False)
    out_path = getattr(args, "out", None)
    json_text = json.dumps(payload, indent=2 if pretty else None)
    if out_path:
        Path(out_path).write_text(json_text)
    else:
        print(json_text)
    return 0


def _create_from_seeds(
    client: AppleMusicClient,
    seeds: list[tuple[str, str]],
    config: PlaylistCreationConfig,
) -> dict:
    """Helper to create a playlist from seed tracks."""
    store = config.storefront
    if not store:
        store = client.ping().get("data", [{}])[0].get("id")
    seeds_copy = list(seeds)
    rng = random.Random(config.shuffle_seed)  # nosec B311 - used for playlist shuffling, not security
    rng.shuffle(seeds_copy)
    seeds_copy = seeds_copy[: min(config.count, len(seeds_copy))]

    tracks_data = []
    resolved = []
    for title, artist in seeds_copy:
        term = f"{title} {artist}"
        results = client.search_songs(term, storefront=store, limit=1)
        if not results:
            continue
        song = results[0]
        tracks_data.append({"id": song.get("id"), "type": song.get("type", "songs") or "songs"})
        resolved.append({"title": title, "artist": artist, "matched": song.get("attributes", {}).get("name")})

    plan = {"storefront": store, "name": config.name, "tracks": resolved}
    if config.dry_run:
        return {"plan": plan}
    if not tracks_data:
        raise AppleMusicError("No tracks resolved from seeds; cannot create playlist.")
    resp = client.create_playlist(config.name, tracks=tracks_data, description=config.description)
    return {"created": resp, "plan": plan}


# Add global arguments for auth
@app.command("ping", help="Verify tokens and return storefront info")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
def cmd_ping(args) -> int:
    """Verify tokens and return storefront info."""
    client = _get_client(args)
    resp = client.ping()
    payload = {"status": "ok", "storefront": resp.get("data", [{}])[0].get("id") if resp else None}
    return _output_json(args, payload)


@app.command("list", help="List playlists (id and name)")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
def cmd_list(args) -> int:
    """List playlists (id and name)."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    payload = {"playlists": [{"id": pl.get("id"), "name": (pl.get("attributes") or {}).get("name")} for pl in playlists]}
    return _output_json(args, payload)


@app.command("tracks", help="List all tracks with playlist context")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
@app.argument("--track-limit", type=int, help="Maximum tracks per playlist to fetch")
def cmd_tracks(args) -> int:
    """List all tracks with playlist context."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    tracks_out = []
    for pl in playlists:
        pl_name = (pl.get("attributes") or {}).get("name")
        pl_id = pl.get("id")
        for tr in client.list_playlist_tracks(pl_id, limit=getattr(args, "track_limit", None)):
            attrs = tr.get("attributes", {}) or {}
            tracks_out.append({
                "playlist_id": pl_id,
                "playlist_name": pl_name,
                "id": tr.get("id"),
                "name": attrs.get("name"),
                "artist": attrs.get("artistName"),
                "album": attrs.get("albumName"),
                "duration_ms": attrs.get("durationInMillis"),
                "track_number": attrs.get("trackNumber"),
            })
    return _output_json(args, {"tracks": tracks_out})


@app.command("export", help="Export playlists and tracks")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
@app.argument("--track-limit", type=int, help="Maximum tracks per playlist to fetch")
def cmd_export(args) -> int:
    """Export playlists and tracks."""
    client = _get_client(args)
    playlists_out = []
    for pl in client.list_library_playlists(limit=getattr(args, "playlist_limit", None)):
        attrs = pl.get("attributes", {}) or {}
        tracks_raw = client.list_playlist_tracks(pl["id"], limit=getattr(args, "track_limit", None))
        tracks = []
        for tr in tracks_raw:
            tr_attrs = tr.get("attributes", {}) or {}
            tracks.append({
                "id": tr.get("id"),
                "name": tr_attrs.get("name"),
                "artist": tr_attrs.get("artistName"),
                "album": tr_attrs.get("albumName"),
                "duration_ms": tr_attrs.get("durationInMillis"),
                "track_number": tr_attrs.get("trackNumber"),
            })
        playlists_out.append({
            "id": pl.get("id"),
            "name": attrs.get("name"),
            "description": (attrs.get("description") or {}).get("standard"),
            "tracks": tracks,
        })
    return _output_json(args, {"playlists": playlists_out})


@app.command("create", help="Create a playlist from preset seeds")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--preset", choices=sorted(PRESETS), default="spanish", help="Preset seed bundle")
@app.argument("--name", help="Playlist name (defaults to preset)")
@app.argument("--description", help="Playlist description (defaults to preset)")
@app.argument("--count", type=int, default=20, help="How many seeds to include (<= len seeds)")
@app.argument("--storefront", help="Storefront code (default: from ping)")
@app.argument("--shuffle-seed", type=int, help="Deterministic shuffle seed (optional)")
def cmd_create(args) -> int:
    """Create a playlist from preset seeds."""
    client = _get_client(args)
    preset = PRESETS[args.preset]
    name = getattr(args, "name", None) or preset["name"]
    desc = args.description if getattr(args, "description", None) is not None else preset["description"]
    config = PlaylistCreationConfig(
        name=name,
        description=desc,
        count=args.count,
        shuffle_seed=getattr(args, "shuffle_seed", None),
        storefront=getattr(args, "storefront", None),
        dry_run=getattr(args, "dry_run", False),
    )
    try:
        payload = _create_from_seeds(
            client=client,
            seeds=preset["seeds"],
            config=config,
        )
    except AppleMusicError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _output_json(args, payload)


def _parse_date(val: str | None) -> datetime:
    """Parse ISO date string, returning datetime.min on error."""
    if not val:
        return datetime.min
    if val.endswith("Z"):
        val = val.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(val)
    except Exception:  # nosec B110 - return sentinel on any parse error
        return datetime.min


def _get_playlist_date(playlist: dict) -> datetime:
    """Extract modification or creation date from playlist."""
    attrs = playlist.get("attributes") or {}
    date_str = attrs.get("lastModifiedDate") or attrs.get("dateAdded")
    return _parse_date(date_str)


def _group_playlists_by_name(playlists: list[dict]) -> dict[str, list[dict]]:
    """Group playlists by name."""
    by_name: dict[str, list[dict]] = {}
    for pl in playlists:
        name = (pl.get("attributes") or {}).get("name") or ""
        by_name.setdefault(name, []).append(pl)
    return by_name


def _find_duplicates_to_remove(pls: list[dict], keep_latest: bool) -> tuple[dict, list[dict]]:
    """Sort playlists by date and return (keep, remove) tuple."""
    sorted_pls = sorted(pls, key=_get_playlist_date, reverse=keep_latest)
    return sorted_pls[0], sorted_pls[1:]


def _delete_playlists(client: AppleMusicClient, playlists: list[dict]) -> list[str]:
    """Delete playlists and return their IDs."""
    deleted = []
    for p in playlists:
        client.delete_playlist(p.get("id"))
        deleted.append(p.get("id"))
    return deleted


@app.command("dedupe", help="Find (and optionally delete) duplicate playlists by name")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--keep", choices=["latest", "first"], default="latest", help="Which duplicate to keep")
@app.argument("--delete", action="store_true", help="Delete duplicates (default: plan only)")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
def cmd_dedupe(args) -> int:
    """Find (and optionally delete) duplicate playlists by name."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    by_name = _group_playlists_by_name(playlists)
    keep_latest = args.keep == "latest"
    should_delete = getattr(args, "delete", False)

    plan = []
    deleted = []
    for name, pls in by_name.items():
        if len(pls) <= 1:
            continue
        keep, remove = _find_duplicates_to_remove(pls, keep_latest)
        plan.append({
            "name": name,
            "keep": keep.get("id"),
            "remove": [p.get("id") for p in remove],
        })
        if should_delete:
            deleted.extend(_delete_playlists(client, remove))

    payload = {"duplicates": plan, "deleted": deleted if should_delete else []}
    return _output_json(args, payload)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    return app.run(argv)

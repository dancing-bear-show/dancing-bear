"""Playlist presets, seed data, and playlist operation helpers for the Apple Music CLI."""

from __future__ import annotations

import random
from datetime import datetime

from .client import AppleMusicClient, AppleMusicError
from .cli_helpers import PlaylistCreationConfig

# Artist name constants (avoids duplicate string literals)
GIPSY_KINGS = "Gipsy Kings"
JUAN_LUIS_GUERRA = "Juan Luis Guerra"
ALIZEE = "Alizée"
MYLENE_FARMER = "Mylène Farmer"
GREAT_BIG_SEA = "Great Big Sea"
STAN_ROGERS = "Stan Rogers"
THE_LONGEST_JOHNS = "The Longest Johns"
LIMP_BIZKIT = "Limp Bizkit"
LINKIN_PARK = "Linkin Park"
RAGE_AGAINST_THE_MACHINE = "Rage Against the Machine"
SYSTEM_OF_A_DOWN = "System Of A Down"
SMASHING_PUMPKINS = "Smashing Pumpkins"
KNIFE_PARTY = "Knife Party"

# Playlist presets for the create command
PRESETS = {
    "spanish": {
        "name": "Spanish Vibes",
        "description": None,
        "seeds": [
            ("Bamboleo", GIPSY_KINGS),
            ("Volare", GIPSY_KINGS),
            ("Djobi Djoba", GIPSY_KINGS),
            ("Baila Me", GIPSY_KINGS),
            ("La Dona", GIPSY_KINGS),
            ("Bem, Bem, Maria", GIPSY_KINGS),
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
            ("Bachata en Fukuoka", JUAN_LUIS_GUERRA),
            ("Burbujas de Amor", JUAN_LUIS_GUERRA),
            ("Eres", "Café Tacvba"),
            ("La Flaca", "Jarabe de Palo"),
            ("Corazón Partío", "Alejandro Sanz"),
            ("La Vida Es un Carnaval", "Celia Cruz"),
            ("Burbujas de Amor", JUAN_LUIS_GUERRA),
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
            ("Bamboleo", GIPSY_KINGS),
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
            ("Moi... Lolita", ALIZEE),
            ("J'en ai marre!", ALIZEE),
            ("Gourmandises", ALIZEE),
            ("Parler tout bas", ALIZEE),
            ("A contre-courant", ALIZEE),
            ("Mademoiselle Juliette", ALIZEE),
            ("Les Collines (Never Leave You)", ALIZEE),
            ("Désenchantée", MYLENE_FARMER),
            ("Sans contrefaçon", MYLENE_FARMER),
            ("Libertine", MYLENE_FARMER),
            ("Pourvu qu'elles soient douces", MYLENE_FARMER),
            ("Sans logique", MYLENE_FARMER),
            ("California", MYLENE_FARMER),
            ("L'Âme-Stram-Gram", MYLENE_FARMER),
            ("Stolen Car", f"{MYLENE_FARMER} Sting"),
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
            ("Ordinary Day", GREAT_BIG_SEA),
            ("Sea Of No Cares", GREAT_BIG_SEA),
            ("When I'm Up", GREAT_BIG_SEA),
            ("Consequence Free", GREAT_BIG_SEA),
            ("The Night Pat Murphy Died", GREAT_BIG_SEA),
            ("General Taylor", GREAT_BIG_SEA),
            ("Mari-Mac", GREAT_BIG_SEA),
            ("Lukey", GREAT_BIG_SEA),
            ("Captain Kidd", GREAT_BIG_SEA),
            ("Ferryland Sealer", GREAT_BIG_SEA),
            ("Barrett's Privateers", STAN_ROGERS),
            ("Northwest Passage", STAN_ROGERS),
            ("The Mary Ellen Carter", STAN_ROGERS),
            ("Forty-Five Years", STAN_ROGERS),
            ("The Log Driver's Waltz", "Kate and Anna McGarrigle"),
            ("The Islander", "Dave Gunning"),
            ("Lighthouse", "The Waifs"),
            ("The Last Saskatchewan Pirate", "The Arrogant Worms"),
            ("Northwest Passage", THE_LONGEST_JOHNS),
            ("Leave Her Johnny", THE_LONGEST_JOHNS),
            ("Wellerman", THE_LONGEST_JOHNS),
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
            ("Break Stuff", LIMP_BIZKIT),
            ("Nookie", LIMP_BIZKIT),
            ("Rollin'", LIMP_BIZKIT),
            ("Last Resort", "Papa Roach"),
            ("Between Angels and Insects", "Papa Roach"),
            ("One Step Closer", LINKIN_PARK),
            ("Papercut", LINKIN_PARK),
            ("Crawling", LINKIN_PARK),
            ("Freak on a Leash", "Korn"),
            ("Got the Life", "Korn"),
            ("Falling Away from Me", "Korn"),
            ("Killing in the Name", RAGE_AGAINST_THE_MACHINE),
            ("Bulls on Parade", RAGE_AGAINST_THE_MACHINE),
            ("Guerrilla Radio", RAGE_AGAINST_THE_MACHINE),
            ("Testify", RAGE_AGAINST_THE_MACHINE),
            ("Chop Suey!", SYSTEM_OF_A_DOWN),
            ("B.Y.O.B.", SYSTEM_OF_A_DOWN),
            ("Toxicity", SYSTEM_OF_A_DOWN),
            ("Sugar", SYSTEM_OF_A_DOWN),
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
            ("Bullet with Butterfly Wings", SMASHING_PUMPKINS),
            ("Zero", SMASHING_PUMPKINS),
            ("Bodies", SMASHING_PUMPKINS),
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
            ("Centipede", KNIFE_PARTY),
            ("Internet Friends", KNIFE_PARTY),
            ("Bonfire", KNIFE_PARTY),
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


def _create_from_seeds(
    client: AppleMusicClient,
    seeds: list[tuple[str, str]],
    config: PlaylistCreationConfig,
) -> dict:
    """Helper to create a playlist from seed tracks."""
    store = config.storefront
    if not store:
        data = client.ping().get("data") or [{}]
        store = data[0].get("id")
    seeds_copy = list(seeds)
    rng = random.Random(config.shuffle_seed)  # nosec B311 - non-security shuffle for playlist ordering
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


def _parse_playlist_date(val: str | None) -> datetime:
    """Parse an ISO date string from Apple Music API; returns datetime.min on failure."""
    if not val:
        return datetime.min
    if val.endswith("Z"):
        val = val.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(val)
    except Exception:  # nosec B110 - return sentinel on any malformed date
        return datetime.min


def _playlist_sort_key(pl: dict) -> datetime:
    """Return a sort key for a playlist based on modification or creation date."""
    attrs = pl.get("attributes") or {}
    date_val = attrs.get("lastModifiedDate") or attrs.get("dateAdded")
    return _parse_playlist_date(date_val)


def _delete_duplicate_playlists(
    client: AppleMusicClient,
    remove: list[dict],
) -> list[str]:
    """Delete a list of duplicate playlists and return their IDs."""
    deleted = []
    for p in remove:
        client.delete_playlist(p.get("id"))
        deleted.append(p.get("id"))
    return deleted

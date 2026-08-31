"""Playlist presets, seed data, and playlist operation helpers for the Apple Music CLI."""

from __future__ import annotations

import random
import re
from datetime import datetime

from .client import AppleMusicCLIError, AppleMusicClient
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
FRANCE_GALL = "France Gall"
FRANCOISE_HARDY = "Françoise Hardy"
SERGE_GAINSBOURG = "Serge Gainsbourg"
JACQUES_DUTRONC = "Jacques Dutronc"
MICHEL_POLNAREFF = "Michel Polnareff"
ANGELE = "Angèle"
CLARA_LUCIANI = "Clara Luciani"
AYA_NAKAMURA = "Aya Nakamura"
COEUR_DE_PIRATE = "Cœur de Pirate"
JOE_DASSIN = "Joe Dassin"
JULIETTE_ARMANET = "Juliette Armanet"
LA_FEMME = "La Femme"
DAFT_PUNK = "Daft Punk"
SEBASTIEN_TELLIER = "Sébastien Tellier"
POLO_AND_PAN = "Polo & Pan"

# How many search results to consider before giving up on a seed. Apple ranks by
# catalog-wide relevance, so the intended track is not always first.
_SEARCH_CANDIDATES = 5

# Tokens too generic to establish that two artist strings refer to the same act.
_ARTIST_STOPWORDS = frozenset({"the", "and", "feat", "featuring", "vs", "with", "de", "la", "le"})

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
            ("Balance Ton Quoi", ANGELE),
            ("Bruxelles je t'aime", ANGELE),
            ("Christine", "Christine and the Queens"),
            ("Tourner Dans Le Vide", "Indila"),
            ("Dernière danse", "Indila"),
            ("Je veux", "Zaz"),
            ("La Grenade", "Clara Luciani"),
            ("Djadja", AYA_NAKAMURA),
            ("Makeba", "Jain"),
            ("Joe le taxi", "Vanessa Paradis"),
            ("Je vole", "Louane"),
            ("Comme des enfants", COEUR_DE_PIRATE),
            ("Week-end à Rome", "Etienne Daho"),
            ("Ella, elle l'a", "France Gall"),
            ("Voyage voyage", "Desireless"),
            ("Les Champs-Élysées", JOE_DASSIN),
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
    "french-chanson": {
        "name": "Chanson & Yé-Yé",
        "description": "French classics from the 60s through the 80s",
        "seeds": [
            ("Ella, elle l'a", FRANCE_GALL),
            ("Poupée de cire, poupée de son", FRANCE_GALL),
            ("Résiste", FRANCE_GALL),
            ("Comment te dire adieu", FRANCOISE_HARDY),
            ("Tous les garçons et les filles", FRANCOISE_HARDY),
            ("Le temps de l'amour", FRANCOISE_HARDY),
            ("Message personnel", FRANCOISE_HARDY),
            ("La Javanaise", SERGE_GAINSBOURG),
            ("Bonnie and Clyde", f"{SERGE_GAINSBOURG} Brigitte Bardot"),
            ("Je t'aime... moi non plus", f"{SERGE_GAINSBOURG} Jane Birkin"),
            ("Il est cinq heures, Paris s'éveille", JACQUES_DUTRONC),
            ("Et moi, et moi, et moi", JACQUES_DUTRONC),
            ("Les Cactus", JACQUES_DUTRONC),
            ("Love Me, Please Love Me", MICHEL_POLNAREFF),
            ("Lettre à France", MICHEL_POLNAREFF),
            ("La Bohème", "Charles Aznavour"),
            ("Emmenez-moi", "Charles Aznavour"),
            ("Non, je ne regrette rien", "Édith Piaf"),
            ("La Vie en rose", "Édith Piaf"),
            ("Les Champs-Élysées", JOE_DASSIN),
            ("Et si tu n'existais pas", JOE_DASSIN),
            ("Voyage voyage", "Desireless"),
            ("Week-end à Rome", "Etienne Daho"),
            ("Marcia Baila", "Les Rita Mitsouko"),
            ("Joe le taxi", "Vanessa Paradis"),
            ("Ne me quitte pas", "Jacques Brel"),
            ("Amsterdam", "Jacques Brel"),
            ("Göttingen", "Barbara"),
            ("Que je t'aime", "Johnny Hallyday"),
            ("Belle-Île-en-Mer", "Laurent Voulzy"),
        ],
    },
    "french-nouvelle-scene": {
        "name": "Nouvelle Scène",
        "description": "Contemporary French pop from the 2010s onward",
        "seeds": [
            ("Balance Ton Quoi", ANGELE),
            ("Bruxelles je t'aime", ANGELE),
            ("Fever", f"{ANGELE} Dua Lipa"),
            ("Tout oublier", f"{ANGELE} Roméo Elvis"),
            ("La Grenade", CLARA_LUCIANI),
            ("Respire encore", CLARA_LUCIANI),
            ("Le Reste", CLARA_LUCIANI),
            ("Le Dernier Jour du Disco", JULIETTE_ARMANET),
            ("L'Amour en Solitaire", JULIETTE_ARMANET),
            ("Qu'importe", JULIETTE_ARMANET),
            ("Djadja", AYA_NAKAMURA),
            ("Copines", AYA_NAKAMURA),
            ("Pookie", AYA_NAKAMURA),
            ("Je veux", "Zaz"),
            ("Dernière danse", "Indila"),
            ("Tourner Dans Le Vide", "Indila"),
            ("Je vole", "Louane"),
            ("Avenir", "Louane"),
            ("Comme des enfants", COEUR_DE_PIRATE),
            ("Je sais pas danser", "Pomme"),
            ("Grandiose", "Pomme"),
            ("Makeba", "Jain"),
            ("Come", "Jain"),
            ("Basique", "Orelsan"),
            ("La pluie", "Orelsan Stromae"),
            ("Auburn", "Lomepal"),
            ("Trop beau", "Lomepal"),
            ("Sur la planche", LA_FEMME),
            ("Où va le monde", LA_FEMME),
            ("Sacré cœur", LA_FEMME),
            ("Ta Reine", ANGELE),
            ("Moi aimer toi", "Vianney"),
            ("Un autre que moi", "Fishbach"),
            ("Mistral gagnant", COEUR_DE_PIRATE),
        ],
    },
    "french-touch": {
        "name": "French Touch",
        "description": "French electronic and dance from Daft Punk to Polo & Pan",
        "seeds": [
            ("One More Time", DAFT_PUNK),
            ("Around the World", DAFT_PUNK),
            ("Digital Love", DAFT_PUNK),
            ("Harder, Better, Faster, Stronger", DAFT_PUNK),
            ("Get Lucky", f"{DAFT_PUNK} Pharrell Williams"),
            ("Instant Crush", f"{DAFT_PUNK} Julian Casablancas"),
            ("Sexy Boy", "Air"),
            ("La Femme d'Argent", "Air"),
            ("Playground Love", "Air"),
            ("Midnight City", "M83"),
            ("Wait", "M83"),
            ("Outro", "M83"),
            ("Lisztomania", "Phoenix"),
            ("1901", "Phoenix"),
            ("If I Ever Feel Better", "Phoenix"),
            ("D.A.N.C.E.", "Justice"),
            ("Genesis", "Justice"),
            ("Safe and Sound", "Justice"),
            ("La Ritournelle", SEBASTIEN_TELLIER),
            ("Roche", SEBASTIEN_TELLIER),
            ("Nana", POLO_AND_PAN),
            ("Canopée", POLO_AND_PAN),
            ("Ani Kuni", POLO_AND_PAN),
            ("Poney Part 1", "Vitalic"),
            ("La Rock 01", "Vitalic"),
            ("Complètement fou", "Yelle"),
            ("Je veux te voir", "Yelle"),
            ("Alors on danse", "Stromae"),
            ("Papaoutai", "Stromae"),
            ("Formidable", "Stromae"),
            ("Louxor J'adore", "Philippe Katerine"),
            ("Flat Beat", "Mr. Oizo"),
            ("Music Sounds Better with You", "Stardust"),
            ("Cassius 1999", "Cassius"),
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


def _normalize_artist_tokens(name: str) -> set[str]:
    """Split an artist string into comparable lowercase word tokens.

    Seeds join collaborators with spaces ("Angèle Dua Lipa") while Apple returns a
    single artistName ("Angèle"), so comparison is token-overlap, not equality.
    Accents are preserved; Apple returns them consistently.
    """
    cleaned = re.sub(r"[^\w\s]", " ", name.casefold())
    return {tok for tok in cleaned.split() if tok not in _ARTIST_STOPWORDS}


def _artists_overlap(seed_artist: str, matched_artist: str) -> bool:
    """Return True when the matched artist plausibly corresponds to the seed artist."""
    seed_tokens = _normalize_artist_tokens(seed_artist)
    matched_tokens = _normalize_artist_tokens(matched_artist)
    if not seed_tokens or not matched_tokens:
        return True  # Nothing to compare on; defer to Apple's ranking.
    return bool(seed_tokens & matched_tokens)


def _pick_matching_song(results: list[dict], seed_artist: str) -> dict | None:
    """Return the first result whose artist matches the seed, else None.

    Apple ranks by relevance across its whole catalog, so a short title can put an
    unrelated track first ("Wait M83" ranks a Ravel concerto above the M83 song).
    Scanning a few candidates recovers the intended track instead of dropping it.
    """
    for song in results:
        matched_artist = (song.get("attributes") or {}).get("artistName")
        if not matched_artist or _artists_overlap(seed_artist, matched_artist):
            return song
    return None


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
    unmatched = []
    for title, artist in seeds_copy:
        term = f"{title} {artist}"
        results = client.search_songs(term, storefront=store, limit=_SEARCH_CANDIDATES)
        if not results:
            unmatched.append({"title": title, "artist": artist, "reason": "no search result"})
            continue
        song = _pick_matching_song(results, artist)
        if song is None:
            top = (results[0].get("attributes") or {})
            unmatched.append({
                "title": title,
                "artist": artist,
                "reason": f"artist mismatch: top result '{top.get('name')}' by '{top.get('artistName')}'",
            })
            continue
        attributes = song.get("attributes") or {}
        tracks_data.append({"id": song.get("id"), "type": song.get("type", "songs") or "songs"})
        resolved.append({"title": title, "artist": artist, "matched": attributes.get("name")})

    plan = {"storefront": store, "name": config.name, "tracks": resolved, "unmatched": unmatched}
    if config.dry_run:
        return {"plan": plan}
    if not tracks_data:
        raise AppleMusicCLIError("No tracks resolved from seeds; cannot create playlist.")
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
        pid = p.get("id")
        if pid is None:
            continue
        client.delete_playlist(pid)
        deleted.append(pid)
    return deleted

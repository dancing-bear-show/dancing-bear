from __future__ import annotations

def register_backup(subparsers, *, f_backup):
    p_backup = subparsers.add_parser("backup", help="Backup Gmail labels and filters to a timestamped folder")
    p_backup.add_argument("--credentials", type=str)
    p_backup.add_argument("--token", type=str)
    p_backup.add_argument("--out-dir", help="Output directory (default backups/<timestamp>)")
    p_backup.set_defaults(func=f_backup)


def register_cache(subparsers, *, f_stats, f_clear, f_prune):
    p_cache = subparsers.add_parser("cache", help="Manage local message cache")
    p_cache.add_argument("--cache", required=True, help="Cache directory root")
    sub_cache = p_cache.add_subparsers(dest="cache_cmd")
    p_cache_stats = sub_cache.add_parser("stats", help="Show cache stats")
    p_cache_stats.set_defaults(func=f_stats)
    p_cache_clear = sub_cache.add_parser("clear", help="Delete entire cache")
    p_cache_clear.set_defaults(func=f_clear)
    p_cache_prune = sub_cache.add_parser("prune", help="Prune files older than N days")
    p_cache_prune.add_argument("--days", type=int, required=True)
    p_cache_prune.set_defaults(func=f_prune)


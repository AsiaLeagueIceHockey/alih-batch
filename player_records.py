import re
import unicodedata
from difflib import SequenceMatcher


STAT_FIELDS = (
    "games_played",
    "points",
    "goals",
    "assists",
    "shots",
    "plus_minus",
    "pim",
)


def normalize_player_name(name):
    """Normalize punctuation and spacing without discarding name order."""
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)


def canonical_player_name(name):
    tokens = re.findall(r"\w+", unicodedata.normalize("NFKC", name).casefold(), flags=re.UNICODE)
    return "".join(sorted(tokens))


def reconcile_player_records(source_records, roster_records, target_season):
    """Match official cumulative records to the existing season roster.

    The roster row is the profile identity. Official cumulative records are
    allowed to update statistics only after every team/jersey key and normalized
    player name matches. Team rosters can change jersey numbers during a season,
    and the official source can temporarily assign the same jersey to two names,
    so identity matching is name-first. A same-jersey spelling fallback is allowed
    only for a single unmatched source/roster pair with high name similarity.
    """
    if not source_records or not roster_records:
        raise RuntimeError("Official individual records and season roster must both be non-empty")

    remaining_roster = list(roster_records)
    matches = {}

    # First pass: punctuation-insensitive and token-order-insensitive names.
    for source_index, source in enumerate(source_records):
        candidates = [
            roster
            for roster in remaining_roster
            if roster["team_id"] == source["team_id"]
            and (
                normalize_player_name(roster["name"]) == normalize_player_name(source["name"])
                or canonical_player_name(roster["name"]) == canonical_player_name(source["name"])
            )
        ]
        if len(candidates) > 1:
            raise RuntimeError(f"Ambiguous roster name match: {source['name']!r}")
        if candidates:
            matches[source_index] = candidates[0]
            remaining_roster.remove(candidates[0])

    # Second pass: tolerate a small spelling drift only when the jersey is unique.
    unmatched_source_indexes = [index for index in range(len(source_records)) if index not in matches]
    for source_index in unmatched_source_indexes:
        source = source_records[source_index]
        source_jersey_count = sum(
            1
            for row in source_records
            if row["team_id"] == source["team_id"]
            and row["jersey_number"] == source["jersey_number"]
        )
        candidates = [
            roster
            for roster in remaining_roster
            if roster["team_id"] == source["team_id"]
            and roster["jersey_number"] == source["jersey_number"]
        ]
        if source_jersey_count != 1 or len(candidates) != 1:
            continue
        similarity = SequenceMatcher(
            None,
            normalize_player_name(source["name"]),
            normalize_player_name(candidates[0]["name"]),
        ).ratio()
        if similarity >= 0.9:
            matches[source_index] = candidates[0]
            remaining_roster.remove(candidates[0])

    # Recovery fallback: a previous sparse upsert may have lost jersey numbers.
    # Accept only one clearly best high-similarity name inside the same team.
    unmatched_source_indexes = [index for index in range(len(source_records)) if index not in matches]
    for source_index in unmatched_source_indexes:
        source = source_records[source_index]
        scored_candidates = [
            (
                SequenceMatcher(
                    None,
                    normalize_player_name(source["name"]),
                    normalize_player_name(roster["name"]),
                ).ratio(),
                roster,
            )
            for roster in remaining_roster
            if roster["team_id"] == source["team_id"]
        ]
        scored_candidates.sort(key=lambda candidate: candidate[0])
        if not scored_candidates:
            continue
        best_score, best_roster = scored_candidates[-1]
        second_score = scored_candidates[-2][0] if len(scored_candidates) > 1 else 0
        if best_score >= 0.9 and best_score - second_score >= 0.05:
            matches[source_index] = best_roster
            remaining_roster.remove(best_roster)

    new_source_indexes = [index for index in range(len(source_records)) if index not in matches]
    if len(new_source_indexes) > 5 or len(remaining_roster) > 10:
        raise RuntimeError(
            "Official roster drift exceeds the guarded update threshold: "
            f"new={len(new_source_indexes)} missing={len(remaining_roster)}"
        )

    updates = []
    for source_index, source in enumerate(source_records):
        roster = matches.get(source_index)
        update = {
            "season": target_season,
            "team_id": source["team_id"],
            "name": roster["name"] if roster else source["name"],
            "jersey_number": source["jersey_number"],
            "position": source["position"],
        }
        update.update({field: source[field] for field in STAT_FIELDS})
        updates.append(update)

    report = {
        "matched": len(matches),
        "new": len(new_source_indexes),
        "missing_from_source": len(remaining_roster),
        "new_names": [source_records[index]["name"] for index in new_source_indexes],
        "missing_names": [roster["name"] for roster in remaining_roster],
    }
    return updates, report


def reconcile_goalie_records(source_records, roster_records, target_season):
    """Map official goalie records to roster identities and allow small additions."""
    updates = []
    new_names = []
    for source in source_records:
        name_candidates = [
            roster
            for roster in roster_records
            if roster["team_id"] == source["team_id"]
            and canonical_player_name(roster["name"]) == canonical_player_name(source["name"])
        ]
        if len(name_candidates) > 1:
            raise RuntimeError(f"Ambiguous goalie name match: {source['name']!r}")

        roster = name_candidates[0] if name_candidates else None
        if roster is None:
            jersey_candidates = [
                candidate
                for candidate in roster_records
                if candidate["team_id"] == source["team_id"]
                and candidate["jersey_number"] == source["jersey_number"]
            ]
            if len(jersey_candidates) == 1:
                similarity = SequenceMatcher(
                    None,
                    normalize_player_name(source["name"]),
                    normalize_player_name(jersey_candidates[0]["name"]),
                ).ratio()
                if similarity >= 0.9:
                    roster = jersey_candidates[0]

        if roster is None:
            new_names.append(source["name"])

        update = dict(source)
        update.update({
            "season": target_season,
            "name": roster["name"] if roster else source["name"],
            "position": "G",
        })
        updates.append(update)

    if len(new_names) > 3:
        raise RuntimeError(f"Official goalie additions exceed threshold: {new_names}")

    return updates, {"matched": len(updates) - len(new_names), "new": len(new_names), "new_names": new_names}

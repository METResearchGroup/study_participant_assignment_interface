def generate_single_assignment_id(
    political_party: str,
    condition: str,
    index: int,
) -> str:
    return f"{political_party}-{condition}-{index:04d}"


def generate_assignment_ids(
    political_party: str,
    condition: str,
    total_assignments: int,
) -> list[str]:
    return [
        generate_single_assignment_id(political_party, condition, i)
        for i in range(total_assignments)
    ]

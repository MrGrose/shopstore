from src.jobs.queue import clear_all_catalog_failed_jobs


# CLI: удаляет failed jobs из catalog-очередей RQ.
def main() -> None:
    counts = clear_all_catalog_failed_jobs()
    for queue_name in ("import", "dom", "finalize", "translation"):
        cleared = counts[queue_name]
        if cleared:
            print(f"{queue_name}: очищено {cleared}")


if __name__ == "__main__":
    main()

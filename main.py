from dotenv import load_dotenv
from typing import Final, List
from tqdm import tqdm
from multiprocessing import Pool, Manager
import os
from natteescraper import NatteeScraper, LoginPostData
import json


def process_chunk(args: tuple) -> List[str]:
    chunk, progress_queue, worker_id, scraper = args
    results: List[str] = []
    session = scraper.clone_session()

    pbar = tqdm(
        chunk,
        desc=f"Worker-{worker_id}",
        position=worker_id + 1,
        leave=False,
    )

    for task in pbar:
        try:
            results.append(task.resolve(session).model_dump_json(indent=2))
        except Exception as e:
            results.append(
                json.dumps({"error": str(e), "task_id": task.task_id}, indent=2)
            )
        progress_queue.put(1)

    return results


def main():
    load_dotenv()
    NUM_PROCESSES: Final = 8
    RESULT_DESTINATION: Final = "result.json"

    # Initialize and validate environment variables
    USERNAME: Final = os.environ.get("GRADER_USERNAME")
    PASSWORD: Final = os.environ.get("GRADER_PASSWORD")

    if not USERNAME or not PASSWORD:
        raise ValueError("GRADER_USERNAME and GRADER_PASSWORD must be set")

    # Initialize scraper
    post_data = LoginPostData(
        utf8="✓",
        authenticity_token=None,
        login=USERNAME,
        password=PASSWORD,
        commit="login",
    )
    scraper = NatteeScraper(post_data)

    # Get and chunk tasks
    partial_tasks = scraper.get_partial_tasks()
    chunk_size = max(1, len(partial_tasks) // NUM_PROCESSES)
    chunks = [
        partial_tasks[i : i + chunk_size]
        for i in range(0, len(partial_tasks), chunk_size)
    ]

    with Manager() as manager:
        progress_queue = manager.Queue()
        total_tasks = len(partial_tasks)

        # Initialize total progress bar first
        total_pbar = tqdm(total=total_tasks, desc="Total Progress", position=0)

        with Pool(processes=NUM_PROCESSES) as pool:
            args = [
                (chunk, progress_queue, i, scraper) for i, chunk in enumerate(chunks)
            ]
            results = pool.map_async(process_chunk, args)

            completed = 0
            while completed < total_tasks:
                progress_queue.get()
                total_pbar.update(1)
                completed += 1

            results = results.get()

    total_pbar.close()

    with open(RESULT_DESTINATION, "w") as f:
        all_results = [
            json.loads(task_result)
            for chunk_results in results
            for task_result in chunk_results
        ]
        json.dump(all_results, f)


if __name__ == "__main__":
    main()

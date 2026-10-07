# Example usage of progress tracker service

<!--toc:start-->

- [Example usage of progress tracker service](#example-usage-of-progress-tracker-service)
  - [Implementation](#implementation)
  - [How to Connect This to Flet UI](#how-to-connect-this-to-flet-ui)
  - [Using Async Flet with asyncio.to_thread()](#using-async-flet-with-asynciotothread)

<!--toc:end-->

## Implementation

```python
def read_epub(file_path: str, tracker: PipelineTracker):
    # Simulate finding 20 items/chapters in EPUB
    total_chapters = 20
    for i in range(1, total_chapters + 1):
        time.sleep(0.05)  # Simulate parsing
        tracker.update_step(
            step_name="read_epub",
            current=i,
            total=total_chapters,
            message=f"Reading chapter {i}/{total_chapters}"
        )


def save_to_db(data: list, tracker: PipelineTracker):
    # Simulate DB insertion batching
    total_records = len(data)
    for i in range(1, total_records + 1):
        time.sleep(0.02)  # Simulate DB query
        tracker.update_step(
            step_name="save_db",
            current=i,
            total=total_records,
            message=f"Saved record {i}/{total_records} to DB"
        )


def embed_vectors(data: list, tracker: PipelineTracker):
    # Simulate CPU/GPU embedding processing
    total_batches = 10
    for i in range(1, total_batches + 1):
        time.sleep(0.15)  # Simulate embedding inference
        tracker.update_step(
            step_name="embed_vectors",
            current=i,
            total=total_batches,
            message=f"Generated embeddings for batch {i}/{total_batches}"
        )


# --- Main Execution Script ---

def main():
    # 1. Define estimated work weight for each phase (sums to 100%)
    STEP_WEIGHTS = {
        "read_epub": 10.0,      # Quick file parsing (10%)
        "save_db": 20.0,        # DB write ops (20%)
        "embed_vectors": 70.0,  # Heavy ML inference (70%)
    }

    # 2. Callback function for UI, CLI, or logging updates
    def display_progress(overall_percent: float, status_msg: str):
        print(f"[{overall_percent:6.2f}%] {status_msg}")

    # 3. Instantiate the tracker
    tracker = PipelineTracker(step_weights=STEP_WEIGHTS, callback=display_progress)

    # 4. Run pipeline
    print("Starting pipeline...")
    read_epub("sample.epub", tracker)

    # Dummy data passed to next stages
    sample_data = [f"doc_{i}" for i in range(30)]
    save_to_db(sample_data, tracker)
    embed_vectors(sample_data, tracker)

    print("Pipeline execution completed!")

if __name__ == "__main__":
    main()

```

## How to Connect This to Flet UI

```py
import flet as ft

def run_pipeline_ui(page: ft.Page):
    progress_bar = ft.ProgressBar(value=0.0)
    status_text = ft.Text("Ready")

    page.add(status_text, progress_bar)

    def on_progress_update(overall_percent: float, message: str):
        # Flet progress bar expects values between 0.0 and 1.0
        progress_bar.value = overall_percent / 100.0
        status_text.value = f"{overall_percent:.1f}% - {message}"
        page.update()

    tracker = PipelineTracker(
        step_weights={"read_epub": 10, "save_db": 20, "embed_vectors": 70},
        callback=on_progress_update
    )

    # Run pipeline...
```

## Using Async Flet with asyncio.to_thread()

```py
import threading
import time
import flet as ft


def main(page: ft.Page):
    page.title = "Cancellable Background Task"
    page.window.width = 500
    page.window.height = 320
    page.padding = 30

    # Thread-safe cancellation signal flag
    cancel_event = threading.Event()

    # UI Controls
    progress_bar = ft.ProgressBar(value=0.0, width=400)
    status_text = ft.Text("Ready", size=15)
    start_btn = ft.ElevatedButton("Start Ingestion")
    cancel_btn = ft.OutlinedButton("Cancel", disabled=True)

    # UI Updater callback for page.run_task
    def update_ui(percent: float, message: str):
        progress_bar.value = percent / 100.0
        status_text.value = f"[{percent:5.1f}%] {message}"
        page.update()

    # Helper to restore button states when finished or cancelled
    def reset_buttons():
        start_btn.disabled = False
        cancel_btn.disabled = True
        page.update()

    # Worker function running in background thread
    def background_pipeline():
        total_items = 40

        for i in range(1, total_items + 1):
            # 1. CHECK CANCELLATION FLAG BEFORE EACH WORK STEP
            if cancel_event.is_set():
                current_pct = ((i - 1) / total_items) * 100
                page.run_task(update_ui, current_pct, "Process cancelled by user.")
                page.run_task(reset_buttons)
                return  # Exit thread cleanly

            # 2. SIMULATE WORK STEP (e.g., embedding chunk)
            time.sleep(0.1)

            # 3. UPDATE PROGRESS
            pct = (i / total_items) * 100
            page.run_task(update_ui, pct, f"Embedding chunk {i}/{total_items}...")

        # Natural completion
        page.run_task(update_ui, 100.0, "Completed successfully!")
        page.run_task(reset_buttons)

    # Event Handlers
    def start_click(e):
        cancel_event.clear()  # Reset flag for new run
        start_btn.disabled = True
        cancel_btn.disabled = False
        progress_bar.value = 0.0
        status_text.value = "Starting pipeline..."
        page.update()

        # Launch background worker
        worker = threading.Thread(target=background_pipeline, daemon=True)
        worker.start()

    def cancel_click(e):
        cancel_event.set()  # Signal worker thread to stop
        cancel_btn.disabled = True
        status_text.value = "Cancelling task..."
        page.update()

    start_btn.on_click = start_click
    cancel_btn.on_click = cancel_click

    page.add(
        ft.Column(
            controls=[
                ft.Text("Task Cancellation Demo", size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                status_text,
                progress_bar,
                ft.Container(height=10),
                ft.Row([start_btn, cancel_btn], spacing=10),
            ],
            spacing=12,
        )
    )


if __name__ == "__main__":
    ft.app(target=main)
```

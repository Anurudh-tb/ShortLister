import { Component, input, output, signal } from '@angular/core';

/** Dashed drag-and-drop area with a hidden file input (keyboard accessible via the label). */
@Component({
  selector: 'app-drop-zone',
  template: `
    <label
      class="drop"
      [class.over]="over()"
      (dragover)="onDragOver($event)"
      (dragleave)="over.set(false)"
      (drop)="onDrop($event)"
    >
      <!-- Static attributes so the OS file dialog always opens in the right mode. -->
      @if (multiple()) {
        <input type="file" [accept]="accept()" multiple (change)="onPick($event)" />
      } @else {
        <input type="file" [accept]="accept()" (change)="onPick($event)" />
      }
      <strong>{{ label() }}</strong> or drop {{ multiple() ? 'them' : 'it' }} here
      <span>{{ hint() }}</span>
    </label>
  `,
})
export class DropZone {
  readonly accept = input('.pdf,.docx,.txt');
  readonly multiple = input(false);
  readonly label = input('Choose a file');
  readonly hint = input('PDF, DOCX or TXT');
  readonly files = output<File[]>();

  protected readonly over = signal(false);

  protected onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.over.set(true);
  }

  protected async onDrop(e: DragEvent): Promise<void> {
    e.preventDefault();
    this.over.set(false);
    const dt = e.dataTransfer;
    if (!dt) return;
    // Entries must be read synchronously, before the drop event's data is released.
    const entries = Array.from(dt.items ?? [])
      .map((item) => item.webkitGetAsEntry?.())
      .filter((entry): entry is FileSystemEntry => !!entry);
    const list =
      this.multiple() && entries.some((entry) => entry.isDirectory)
        ? (await Promise.all(entries.map(readEntry))).flat() // a dropped folder adds every file inside it
        : Array.from(dt.files);
    if (list.length) this.files.emit(this.multiple() ? list : list.slice(0, 1));
  }

  protected onPick(e: Event): void {
    const el = e.target as HTMLInputElement;
    const list = Array.from(el.files ?? []);
    if (list.length) this.files.emit(list);
    el.value = ''; // allow picking the same file again
  }
}

/** All files under a dropped file or folder entry, including subfolders. */
async function readEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    return new Promise((resolve) => (entry as FileSystemFileEntry).file((f) => resolve([f]), () => resolve([])));
  }
  if (!entry.isDirectory) return [];
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  // readEntries returns results in batches; keep reading until it returns an empty batch.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve) => reader.readEntries(resolve, () => resolve([])));
    if (!batch.length) break;
    children.push(...batch);
  }
  return (await Promise.all(children.map(readEntry))).flat();
}

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
      @if (folder()) {
        <input type="file" webkitdirectory multiple (change)="onPick($event)" />
      } @else if (multiple()) {
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
  /** Pick a whole folder (all files inside it, including subfolders). */
  readonly folder = input(false);
  readonly label = input('Choose a file');
  readonly hint = input('PDF, DOCX or TXT');
  readonly files = output<File[]>();

  protected readonly over = signal(false);

  protected onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.over.set(true);
  }

  protected onDrop(e: DragEvent): void {
    e.preventDefault();
    this.over.set(false);
    const list = Array.from(e.dataTransfer?.files ?? []);
    if (list.length) this.files.emit(this.multiple() ? list : list.slice(0, 1));
  }

  protected onPick(e: Event): void {
    const el = e.target as HTMLInputElement;
    const list = Array.from(el.files ?? []);
    if (list.length) this.files.emit(list);
    el.value = ''; // allow picking the same file again
  }
}

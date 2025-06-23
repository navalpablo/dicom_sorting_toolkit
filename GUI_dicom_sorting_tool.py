#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DICOM Sorting Toolkit GUI

Adds:
• In-place decompression panel
• Explicit-VR-Little-Endian conversion panel driven by pure-Python walk()
"""

# --------------------------------------------------
# imports
# --------------------------------------------------
import sys, os, logging, multiprocessing
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QRadioButton, QButtonGroup, QMessageBox,
    QGroupBox, QCheckBox, QProgressDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

import pydicom
from dicom_sorting_tool import sort_dicom, decompress_dataset, read_id_correlation
from to_explicit_pydicom import walk        # <-- pure-Python converter (no DCMTK)

# --------------------------------------------------
# worker threads
# --------------------------------------------------
class DecompressionThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, input_dir: str):
        super().__init__()
        self.input_dir = input_dir

    def run(self):
        try:
            total_files = sum(len(fs) for _, _, fs in os.walk(self.input_dir))
            processed = decompressed = skipped = 0

            for root, _, files in os.walk(self.input_dir):
                for f in files:
                    path = os.path.join(root, f)
                    try:
                        ds = pydicom.dcmread(path)
                        if ds.file_meta.TransferSyntaxUID.is_compressed:
                            ds = decompress_dataset(ds)
                            ds.save_as(path)
                            decompressed += 1
                        else:
                            skipped += 1
                    except pydicom.errors.InvalidDicomError:
                        skipped += 1
                    except Exception as e:
                        self.error.emit(f"Error processing {path} — {e}")
                        skipped += 1
                    processed += 1
                    self.progress.emit(int(processed / total_files * 100))

            logging.info(f"Decompression done — ok:{decompressed}  skipped:{skipped}")
            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))


class SortingThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, *a):
        super().__init__()
        (self.input_dir, self.output_dir, self.anonymize, self.id_map,
         self.decompress, self.strict_anonymize, self.skip_derived,
         self.skip_burned, self.id_from_name, self.anonymize_birth_date,
         self.anonymize_acquisition_date, self.preserve_private_tags,
         self.anonymize_accession) = a
        self.cancel_flag = multiprocessing.Value('b', False)

    def run(self):
        try:
            sort_dicom(
                self.input_dir, self.output_dir, self.anonymize, self.id_map,
                self.decompress, self.strict_anonymize, self.skip_derived,
                self.skip_burned, self.id_from_name, self.anonymize_birth_date,
                self.anonymize_acquisition_date, self.preserve_private_tags,
                self.anonymize_accession,
                progress_callback=self.progress.emit,
                cancel_flag=self.cancel_flag
            )
            if not self.cancel_flag.value:
                self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        self.cancel_flag.value = True


class ExplicitThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, input_dir: str):
        super().__init__()
        self.input_dir = input_dir

    def run(self):
        try:
            # Collect all file paths
            files = [os.path.join(r, f)
                     for r, _, fs in os.walk(self.input_dir) for f in fs]
            total = len(files)
            for i, path in enumerate(files, start=1):
                try:
                    ds = pydicom.dcmread(path, force=True)
                    if ds.file_meta.TransferSyntaxUID.is_compressed:
                        ds.decompress()
                    from pydicom.uid import ExplicitVRLittleEndian
                    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                    ds.is_little_endian = True
                    ds.is_implicit_VR = False
                    ds.save_as(path, write_like_original=False)
                except (AttributeError, TypeError, ValueError):
                    # Do nothing; skip problematic files silently
                    continue
                except Exception:
                    # Log unexpected exceptions, but still continue
                    logging.debug(f"Explicit conversion skipped for {path}", exc_info=True)
                    continue

                self.progress.emit(int(i / total * 100))

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# --------------------------------------------------
# GUI
# --------------------------------------------------
class DicomSortingGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.sorting_thread   = None
        self.decomp_thread    = None
        self.exp_thread       = None
        self.progress_dialog  = None
        self.initUI()

        logging.basicConfig(filename='dicom_sorting_gui.log',
                            level=logging.DEBUG,
                            format='%(asctime)s %(levelname)s %(message)s')

    # ---------- UI layout ----------
    def initUI(self):
        layout = QVBoxLayout()

        # ==============================================================
        # 1. SORTING PANEL
        # ==============================================================
        sorting_group = QGroupBox("DICOM Sorting")
        sorting_layout = QVBoxLayout()

        # input / output directories
        self.input_edit  = self._dir_row("Input Directory:", sorting_layout)
        self.output_edit = self._dir_row("Output Directory:", sorting_layout)

        # anonymisation radio buttons
        anon_layout = QHBoxLayout()
        self.anon_group = QButtonGroup()
        self.no_anon_radio    = QRadioButton("No anonymization")
        self.basic_anon_radio = QRadioButton("Basic")
        self.strict_anon_radio= QRadioButton("Strict")
        for rb in (self.no_anon_radio, self.basic_anon_radio, self.strict_anon_radio):
            self.anon_group.addButton(rb)
            anon_layout.addWidget(rb)
        self.no_anon_radio.setChecked(True)
        anon_info = QPushButton("?"); anon_info.clicked.connect(self.show_anon_info)
        anon_layout.addWidget(anon_info)
        sorting_layout.addLayout(anon_layout)

        # ID correlation file
        self.id_edit = self._file_row("ID Correlation File:", sorting_layout, self.show_id_info)

        # checkboxes
        self.id_from_name_check          = self._add_cb("Read original ID from PatientName", sorting_layout)
        self.decompress_check            = self._add_cb("Decompress", sorting_layout)
        self.skip_derived_check          = self._add_cb("Skip Secondary/Derived images", sorting_layout)
        self.skip_burned_check           = self._add_cb("Skip Burned-in images", sorting_layout)
        self.preserve_private_tags_check = self._add_cb("Preserve Private Tags (strict mode)", sorting_layout)
        self.anonymize_birth_date_check  = self._add_cb("Anonymize Birth Date to 01-Jan", sorting_layout)
        self.anonymize_acquisition_date_check = self._add_cb("Anonymize Acquisition Date to 01-Jan", sorting_layout)
        self.anonymize_accession_check   = self._add_cb("Anonymize Accession Number", sorting_layout)

        # execute sorting
        sort_btn = QPushButton("Execute Sorting")
        sort_btn.clicked.connect(self.execute_sorting)
        sorting_layout.addWidget(sort_btn)

        sorting_group.setLayout(sorting_layout)
        layout.addWidget(sorting_group)

        # ==============================================================
        # 2. IN-PLACE DECOMPRESSION PANEL
        # ==============================================================
        decomp_group = QGroupBox("In-place Decompression")
        decomp_layout = QVBoxLayout()
        self.decomp_input_edit = self._dir_row("Input Directory:", decomp_layout)
        decomp_btn = QPushButton("Execute Decompression")
        decomp_btn.clicked.connect(self.execute_decompression)
        decomp_layout.addWidget(decomp_btn)
        decomp_group.setLayout(decomp_layout)
        layout.addWidget(decomp_group)

        # ==============================================================
        # 3. EXPLICIT-VR-LE CONVERSION PANEL
        # ==============================================================
        explicit_group = QGroupBox("Convert to Explicit VR Little Endian  (SLOW!)")
        explicit_layout = QVBoxLayout()
        self.exp_input_edit = self._dir_row("Input Directory:", explicit_layout)
        exp_btn = QPushButton("Execute Conversion")
        exp_btn.clicked.connect(self.execute_explicit)
        explicit_layout.addWidget(exp_btn)
        explicit_group.setLayout(explicit_layout)
        layout.addWidget(explicit_group)

        # --------------------------------------------------
        # footer
        # --------------------------------------------------
        help_btn = QPushButton("Help"); help_btn.clicked.connect(self.show_help)
        layout.addWidget(help_btn)

        info = QLabel("© 2025 Pablo Naval Baudin")
        info.setAlignment(Qt.AlignCenter); layout.addWidget(info)

        disclaimer = QLabel("Internal tool. Not validated against DICOM standard. Use at your own risk.")
        disclaimer.setAlignment(Qt.AlignCenter); disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)

        self.setLayout(layout)
        self.setWindowTitle("DICOM Sorting Toolkit v0.1.5.0")
        self.show()

    # ---------- convenience layout helpers ----------
    def _dir_row(self, label, parent_layout):
        lay = QHBoxLayout()
        lay.addWidget(QLabel(label))
        edit = QLineEdit(); lay.addWidget(edit)
        btn  = QPushButton("Browse"); btn.clicked.connect(lambda: self.browse_directory(edit))
        lay.addWidget(btn)
        parent_layout.addLayout(lay)
        return edit

    def _file_row(self, label, parent_layout, info_slot=None):
        lay = QHBoxLayout()
        lay.addWidget(QLabel(label))
        edit = QLineEdit(); lay.addWidget(edit)
        btn  = QPushButton("Browse"); btn.clicked.connect(lambda: self.browse_file(edit))
        lay.addWidget(btn)
        if info_slot:
            i_btn = QPushButton("?"); i_btn.clicked.connect(info_slot)
            lay.addWidget(i_btn)
        parent_layout.addLayout(lay)
        return edit

    def _add_cb(self, text, parent_layout):
        cb = QCheckBox(text); parent_layout.addWidget(cb); return cb

    # ---------- common browse helpers ----------
    def browse_directory(self, line_edit):
        d = QFileDialog.getExistingDirectory(self, "Select Directory")
        if d: line_edit.setText(d)

    def browse_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(self, "Select File")
        if f: line_edit.setText(f)

# ───────────────────────────────────────────────────────────────────────────────
#  Replace every   def …(): ...    placeholder with the real implementation
# ───────────────────────────────────────────────────────────────────────────────

    # ---------- information pop-ups ----------
    def show_anon_info(self):
        QMessageBox.information(self, "Anonymization Info",
            "No Anonymization: No changes to patient information.\n\n"
            "Basic Anonymization:\n"
            "- Anonymizes: PatientName, PatientID\n"
            "- If no ID correlation file is provided, a random 8-character ID is used.\n\n"
            "Strict Anonymization (adds to Basic):\n"
            "- Anonymizes all Patient-* tags, removes private tags,\n"
            "- Creates dummy UIDs, etc.\n\n"
            "Extras: toggle birth/acquisition date, accession number, preserve private tags.")

    def show_id_info(self):
        QMessageBox.information(self, "ID Correlation File",
            "Tab-separated or CSV with two columns:\n"
            "   oldID    newID\n"
            "Used to map original PatientIDs (or PatientNames) to new IDs.")

    def show_help(self):
        QMessageBox.information(self, "Help",
            "1. **Sorting** – choose input & output, anonymization level, options.\n"
            "2. **In-place Decompression** – pick a folder, all DICOMs are decompressed.\n"
            "3. **Explicit VR Conversion** – pick a folder, every DICOM is rewritten\n"
            "   as Explicit VR Little Endian (slow & grows files).\n\n"
            "See the GitHub repo for details.")

    # ---------- sorting ----------
    def execute_sorting(self):
        inp  = self.input_edit.text()
        outp = self.output_edit.text()
        if not inp or not outp:
            QMessageBox.warning(self, "Error", "Select both input and output directories.")
            return

        basic  = self.basic_anon_radio.isChecked()
        strict = self.strict_anon_radio.isChecked()
        id_map = read_id_correlation(self.id_edit.text()) if self.id_edit.text() else None

        self.progress_dialog = QProgressDialog("Sorting …", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.canceled.connect(self.cancel_sorting)
        self.progress_dialog.show()

        self.sorting_thread = SortingThread(
            inp, outp,
            basic or strict,
            id_map,
            self.decompress_check.isChecked(),
            strict,
            self.skip_derived_check.isChecked(),
            self.skip_burned_check.isChecked(),
            self.id_from_name_check.isChecked(),
            self.anonymize_birth_date_check.isChecked(),
            self.anonymize_acquisition_date_check.isChecked(),
            self.preserve_private_tags_check.isChecked(),
            self.anonymize_accession_check.isChecked()
        )
        self.sorting_thread.progress.connect(self.update_sorting_progress)
        self.sorting_thread.finished.connect(self.sorting_finished)
        self.sorting_thread.error.connect(self.sorting_error)
        self.sorting_thread.start()

    def cancel_sorting(self):
        if self.sorting_thread and self.sorting_thread.isRunning():
            self.sorting_thread.cancel()
            self.sorting_thread.wait()
        if self.progress_dialog:
            self.progress_dialog.close()

    def update_sorting_progress(self, v):
        if self.progress_dialog and not self.progress_dialog.wasCanceled():
            self.progress_dialog.setValue(v)

    def sorting_finished(self):
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.information(self, "Success", "Sorting completed.")
        self.sorting_thread = self.progress_dialog = None

    def sorting_error(self, msg):
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.critical(self, "Error", f"Sorting failed:\n{msg}")
        self.sorting_thread = self.progress_dialog = None

    # ---------- decompression ----------
    def execute_decompression(self):
        d = self.decomp_input_edit.text()
        if not d:
            QMessageBox.warning(self, "Error", "Select an input directory.")
            return

        self.decomp_thread = DecompressionThread(d)
        self.decomp_thread.progress.connect(self.update_progress)
        self.decomp_thread.finished.connect(self.decompression_finished)
        self.decomp_thread.error.connect(self.decompression_error)
        self.decomp_thread.start()

        self.progress_dialog = QProgressDialog("Decompressing …", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.canceled.connect(self.decomp_thread.terminate)
        self.progress_dialog.show()

    def update_progress(self, v):
        if self.progress_dialog:
            self.progress_dialog.setValue(v)

    def decompression_finished(self):
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.information(self, "Success", "Decompression completed.")
        self.decomp_thread = self.progress_dialog = None

    def decompression_error(self, msg):
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.critical(self, "Error", f"Decompression failed:\n{msg}")
        self.decomp_thread = self.progress_dialog = None



    # ---------- explicit VR conversion ----------

    def execute_explicit(self):
        d = self.exp_input_edit.text()
        if not d:
            QMessageBox.warning(self, "Error", "Please select an input directory.")
            return
        if QMessageBox.question(self, "Confirm – slow operation",
                                "Conversion can be slow and will increase file size.\nProceed?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        self.exp_thread = ExplicitThread(d)
        self.exp_thread.progress.connect(self.update_sorting_progress)  # reuse existing progress slot
        self.exp_thread.finished.connect(self.explicit_finished)
        self.exp_thread.error.connect(self.explicit_error)
        self.exp_thread.start()

        self.progress_dialog = QProgressDialog("Converting …", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.canceled.connect(self.exp_thread.terminate)
        self.progress_dialog.show()


    def explicit_finished(self):
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.information(self, "Success", "Conversion completed.")
        self.exp_thread = self.progress_dialog = None

    def explicit_error(self, msg):
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.critical(self, "Error", f"Conversion failed:\n{msg}")
        self.exp_thread = self.progress_dialog = None


# --------------------------------------------------
# main
# --------------------------------------------------
if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    gui = DicomSortingGUI()
    sys.exit(app.exec_())

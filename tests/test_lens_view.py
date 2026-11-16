import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtTest import QTest

from lens_view import LensViewWindow, has_split_lenses
from main_window import MainWindow


CAMERA = {'id': 7, 'name': 'Garden', 'model': 'D57',
          'url': 'v380://admin:test-only@192.0.2.1?device_id=123',
          'ptz': True, 'ptz_backend': 'v380'}


class LensViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.top = LensViewWindow(7, 'Garden', 'upper')
        self.bottom = LensViewWindow(7, 'Garden', 'lower', ptz=True)
        self.frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.frame[:100] = (0, 0, 255)
        self.frame[100:] = (255, 0, 0)
        for window in (self.top, self.bottom):
            window.show()
            window.update_frame(self.frame)
        self.app.processEvents()

    def tearDown(self):
        self.top.close()
        self.bottom.close()
        self.app.processEvents()

    def test_only_known_d57_is_split(self):
        self.assertTrue(has_split_lenses(CAMERA))
        self.assertFalse(has_split_lenses(dict(CAMERA, model='other')))
        self.assertFalse(has_split_lenses(dict(CAMERA, url='rtsp://192.0.2.1/stream')))

    def test_distinct_halves_share_source_without_modification(self):
        self.assertEqual(self.top.frame.shape, (100, 160, 3))
        self.assertEqual(self.bottom.frame.shape, (100, 160, 3))
        self.assertTrue(np.shares_memory(self.top.frame, self.frame))
        self.assertTrue(np.shares_memory(self.bottom.frame, self.frame))
        for window, color in ((self.top, '#ff0000'), (self.bottom, '#0000ff')):
            rect = window.label.frame_display_rect()
            image = window.label.pixmap().toImage()
            self.assertEqual(image.pixelColor(rect.center()).name(), color)
        self.top.zoom(2)
        np.testing.assert_array_equal(self.frame[:100], np.full((100, 160, 3), (0, 0, 255), dtype=np.uint8))

    def test_zoom_and_reset_are_independent(self):
        self.top.zoom(2)
        self.assertEqual(self.top.crop_rect.size().width(), 80)
        self.assertIsNone(self.bottom.crop_rect)
        self.bottom.zoom(4)
        bottom_crop = QRect(self.bottom.crop_rect)
        QTest.mouseClick(self.top.reset_button, Qt.MouseButton.LeftButton)
        self.assertIsNone(self.top.crop_rect)
        self.assertEqual(self.bottom.crop_rect, bottom_crop)
        self.bottom.label.double_clicked.emit(7)
        self.assertIsNone(self.bottom.crop_rect)

    def test_selection_maps_letterbox_and_nested_crop(self):
        rect = self.bottom.label.frame_display_rect()
        selection = QRect(rect.x() + rect.width() // 4, rect.y() + rect.height() // 4,
                          rect.width() // 2, rect.height() // 2)
        self.bottom.label.region_selected.emit(7, selection)
        crop = self.bottom.crop_rect
        self.assertAlmostEqual(crop.x(), 40, delta=1)
        self.assertAlmostEqual(crop.y(), 25, delta=1)
        self.assertAlmostEqual(crop.width(), 80, delta=1)
        self.assertAlmostEqual(crop.height(), 50, delta=1)
        rect = self.bottom.label.frame_display_rect()
        self.bottom.label.region_selected.emit(7, QRect(rect.x(), rect.y(), rect.width() // 2, rect.height() // 2))
        self.assertTrue(crop.contains(self.bottom.crop_rect))
        self.assertLess(self.bottom.crop_rect.width(), crop.width())
        self.assertIsNone(self.top.crop_rect)

    def test_wheel_zooms_only_target_window(self):
        from PyQt6.QtCore import QPoint
        pos = QPointF(self.top.label.frame_display_rect().center())
        event = QWheelEvent(pos, pos, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(self.top.label, event)
        self.assertIsNotNone(self.top.crop_rect)
        self.assertIsNone(self.bottom.crop_rect)

    def test_zoom_survives_frames_and_resize_but_resets_on_resolution_change(self):
        self.top.zoom(2)
        crop = QRect(self.top.crop_rect)
        self.top.update_frame(self.frame.copy())
        self.top.resize(900, 600)
        self.app.processEvents()
        self.assertEqual(self.top.crop_rect, crop)
        self.top.update_frame(np.zeros((720, 640, 3), dtype=np.uint8))
        self.assertIsNone(self.top.crop_rect)
        self.assertEqual(self.top.frame.shape, (360, 640, 3))

    def test_odd_height_and_invalid_frames(self):
        odd = np.zeros((201, 160, 3), dtype=np.uint8)
        self.top.update_frame(odd)
        self.bottom.update_frame(odd)
        self.assertEqual(self.top.frame.shape[0] + self.bottom.frame.shape[0], 201)
        self.bottom.update_frame(np.zeros((1, 160, 3), dtype=np.uint8))
        self.assertIsNone(self.bottom.frame)
        self.assertFalse(self.bottom.ptz_pad.isEnabled())

    def test_ptz_only_lower_and_stops_on_deactivate_collapse_close(self):
        self.assertIsNone(self.top.ptz_pad)
        move, stop = MagicMock(), MagicMock()
        self.bottom.move_requested.connect(move)
        self.bottom.stop_requested.connect(stop)
        QTest.mousePress(self.bottom.ptz_pad.buttons['left'], Qt.MouseButton.LeftButton)
        move.assert_called_once_with('left')
        QTest.mouseRelease(self.bottom.ptz_pad.buttons['left'], Qt.MouseButton.LeftButton)
        stop.assert_called()
        for action in (
            lambda: QApplication.sendEvent(self.bottom, QEvent(QEvent.Type.WindowDeactivate)),
            lambda: self.bottom.ptz_pad.toggle_btn.setChecked(False),
            self.bottom.close,
        ):
            stop.reset_mock()
            action()
            stop.assert_called()

    def test_disconnect_clears_stale_image_and_disables_ptz(self):
        self.bottom.set_status(False, 'Disconnected')
        self.assertIsNone(self.bottom.frame)
        self.assertTrue(self.bottom.label.pixmap().isNull())
        self.assertFalse(self.bottom.ptz_pad.isEnabled())
        self.bottom.update_frame(self.frame)
        self.assertTrue(self.bottom.ptz_pad.isEnabled())


class LensIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.main = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(self.main)
        self.main.cameras = [dict(CAMERA)]
        self.main.lens_windows = {}
        self.main.camera_threads = {}
        self.main.camera_widgets = {}
        self.main._ptz_controllers = {}
        self.main._closing = False
        self.main.selected_camera_id = None
        self.main.selected_camera_ids = []
        self.main.zoomed_camera_id = None
        self.main.detection_worker = None

    def tearDown(self):
        self.main._close_lens_windows()
        self.main.deleteLater()
        self.app.processEvents()

    def test_two_windows_one_thread_and_shared_frame(self):
        with patch('main_window.CameraThread') as factory, patch.object(self.main, '_prebuffer_seconds', return_value=0):
            thread = self.main._start_camera_thread(CAMERA)
            self.main.start_single_stream(7)
            factory.assert_called_once()
            thread.start.assert_called_once()
        self.assertEqual(set(self.main.lens_windows), {(7, 'upper'), (7, 'lower')})
        frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.update_camera_frame(frame, 7)
        for window in self.main.lens_windows.values():
            self.assertTrue(np.shares_memory(window.frame, frame))
        self.main.selected_camera_id = 7
        self.assertIsNone(self.main._active_ptz_camera_id())

    def test_close_one_window_keeps_stream_and_other_view_then_reopens(self):
        thread = MagicMock()
        self.main.camera_threads[7] = thread
        self.main._show_lens_windows(7)
        bottom = self.main.lens_windows[(7, 'lower')]
        self.main.lens_windows[(7, 'upper')].close()
        self.assertNotIn((7, 'upper'), self.main.lens_windows)
        self.assertIs(self.main.lens_windows[(7, 'lower')], bottom)
        thread.stop.assert_not_called()
        self.main._show_lens_windows(7)
        self.assertEqual(len(self.main.lens_windows), 2)
        self.assertIs(self.main.lens_windows[(7, 'lower')], bottom)

    def test_ptz_routes_to_shared_controller_even_when_other_camera_selected(self):
        self.main.camera_threads[7] = MagicMock()
        controller = MagicMock()
        self.main._ptz_controllers[7] = controller
        self.main._show_lens_windows(7)
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        self.main.selected_camera_id = 99
        bottom = self.main.lens_windows[(7, 'lower')]
        bottom.move_requested.emit('right')
        controller.move.assert_called_once_with('right')
        bottom.close()
        controller.stop.assert_called()

    def test_stop_closes_both_windows(self):
        thread = MagicMock()
        self.main.camera_threads[7] = thread
        self.main._show_lens_windows(7)
        self.assertTrue(self.main._stop_camera_thread(7))
        self.assertFalse(self.main.lens_windows)
        self.assertNotIn(7, self.main.camera_threads)

    def test_ptz_opt_out_and_other_models(self):
        self.main.cameras[0]['ptz'] = False
        self.main._show_lens_windows(7)
        self.assertIsNone(self.main.lens_windows[(7, 'lower')].ptz_pad)
        self.main._close_lens_windows()
        self.main.cameras[0]['model'] = 'other'
        self.main._show_lens_windows(7)
        self.assertFalse(self.main.lens_windows)

    def test_disconnect_updates_both_views_without_new_thread(self):
        self.main._show_lens_windows(7)
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        self.main.update_camera_status(False, 7, 'Reconnecting')
        self.assertTrue(all(w.frame is None for w in self.main.lens_windows.values()))
        self.assertFalse(self.main.camera_threads)

    def test_full_frame_reaches_preview_and_detection_unchanged(self):
        self.main._show_lens_windows(7)
        self.main.cameras[0]['detection_enabled'] = True
        self.main.detection_worker = MagicMock()
        widget = MagicMock()
        self.main.camera_widgets[7] = widget
        frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.update_camera_frame(frame, 7)
        self.assertIs(widget.update_frame.call_args.args[0], frame)
        self.assertIs(self.main.detection_worker.submit_frame.call_args.args[2], frame)
        self.assertEqual(frame.shape, (200, 160, 3))

    def test_disconnect_does_not_restore_stale_cached_frame(self):
        widget = MagicMock()
        widget.last_frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.camera_widgets[7] = widget
        self.main.camera_threads[7] = MagicMock()
        self.main._show_lens_windows(7)
        self.main.update_camera_status(False, 7, 'Reconnecting')
        self.assertIsNone(widget.last_frame)
        self.main._close_lens_windows()
        self.main._show_lens_windows(7)
        self.assertTrue(all(w.frame is None for w in self.main.lens_windows.values()))

    def test_start_ignores_cached_frame_from_previous_session(self):
        widget = MagicMock()
        widget.last_frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.camera_widgets[7] = widget
        with patch('main_window.CameraThread'), patch.object(self.main, '_prebuffer_seconds', return_value=0):
            self.main._start_camera_thread(CAMERA)
        self.assertTrue(all(w.frame is None for w in self.main.lens_windows.values()))

    def test_click_reopens_windows_in_multi_view_without_extra_thread(self):
        self.main.selected_camera_ids = [7, 8]
        self.main.camera_threads[7] = MagicMock()
        with patch('main_window.CameraThread') as factory:
            self.main.select_camera(7)
            factory.assert_not_called()
        self.assertEqual(len(self.main.lens_windows), 2)


if __name__ == '__main__':
    unittest.main()

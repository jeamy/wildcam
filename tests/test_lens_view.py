import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtTest import QTest

from lens_view import LensView, has_split_lenses
from main_window import MainWindow
from widgets import PreviewLabel


CAMERA = {'id': 7, 'name': 'Garden', 'model': 'D57',
          'url': 'v380://admin:test-only@192.0.2.1?device_id=123',
          'ptz': True, 'ptz_backend': 'v380'}


class LensViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.host.resize(1440, 470)
        self.top = LensView(7, 'Garden', 'upper', parent=self.host)
        self.bottom = LensView(7, 'Garden', 'lower', ptz=True, parent=self.host)
        self.bottom.move(720, 0)
        self.host.show()
        self.frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.frame[:100] = (0, 0, 255)
        self.frame[100:] = (255, 0, 0)
        for window in (self.top, self.bottom):
            window.resize(720, 470)
            window.show()
            window.update_frame(self.frame)
        self.app.processEvents()

    def tearDown(self):
        self.top.close()
        self.bottom.close()
        self.host.close()
        self.host.deleteLater()
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
        self.top.reset_zoom()
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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, kwargs in (
            ('main_window.DEFAULT_RECORDING_PATH', {'new': self.temp.name}),
            ('main_window.MainWindow.load_config', {}),
            ('main_window.MainWindow.save_config', {}),
            ('main_window.MainWindow.refresh_proxy_status', {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.main = MainWindow()
        self.main.cameras = [dict(CAMERA)]
        for cid in (8, 9, 10):
            self.main.cameras.append({'id': cid, 'name': f'Camera {cid}', 'url': 'rtsp://192.0.2.1/video'})
        for camera in self.main.cameras:
            self.main._get_or_create_camera_widget(camera)
            thread = MagicMock()
            thread.measured_fps = 0.0
            self.main.camera_threads[camera['id']] = thread
        self.main.resize(1400, 900)
        self.main.show()

    def tearDown(self):
        self.main.detection_worker = None
        for thread in self.main.camera_threads.values():
            thread.isRunning.return_value = False
        self.main.close()
        self.main.deleteLater()
        self.app.processEvents()

    def select(self, ids):
        self.main.selected_camera_ids = list(ids)
        self.main._rebuild_multi_view_layout()
        self.app.processEvents()

    def test_two_embedded_tiles_one_thread_and_shared_frame(self):
        self.select([7])
        del self.main.camera_threads[7]
        with patch('main_window.CameraThread') as factory, patch.object(self.main, '_prebuffer_seconds', return_value=0):
            thread = self.main._start_camera_thread(CAMERA)
            self.main.start_single_stream(7)
            factory.assert_called_once()
            thread.start.assert_called_once()
        self.assertEqual(set(self.main.lens_views), {(7, 'upper'), (7, 'lower')})
        frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.update_camera_frame(frame, 7)
        for view in self.main.lens_views.values():
            self.assertTrue(np.shares_memory(view.frame, frame))
            self.assertFalse(view.isWindow())
            self.assertIs(view.window(), self.main)
        self.main.selected_camera_id = 7
        self.assertIsNone(self.main._active_ptz_camera_id())

    def test_close_one_tile_keeps_stream_and_other_view_then_reopens(self):
        self.select([7, 8])
        thread = self.main.camera_threads[7]
        top = self.main.lens_views[(7, 'upper')]
        bottom = self.main.lens_views[(7, 'lower')]
        self.main.multi_view_close_buttons[(7, 'upper')][1].click()
        self.assertTrue(top.isHidden())
        self.assertIs(self.main.lens_views[(7, 'lower')], bottom)
        self.assertTrue(bottom.isVisible())
        thread.stop.assert_not_called()
        self.main.select_camera(7)
        self.assertTrue(top.isVisible())
        self.assertIs(self.main.lens_views[(7, 'lower')], bottom)

    def test_ptz_routes_to_shared_controller_even_when_other_camera_selected(self):
        self.select([7, 8])
        controller = MagicMock()
        self.main._ptz_controllers[7] = controller
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        self.main.selected_camera_id = 99
        bottom = self.main.lens_views[(7, 'lower')]
        bottom.move_requested.emit('right')
        controller.move.assert_called_once_with('right')
        self.main.multi_view_close_buttons[(7, 'lower')][1].click()
        controller.stop.assert_called()

    def test_stop_clears_both_tiles_without_removing_selection(self):
        self.select([7])
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        self.assertTrue(self.main._stop_camera_thread(7))
        self.assertEqual(len(self.main.lens_views), 2)
        self.assertTrue(all(w.frame is None for w in self.main.lens_views.values()))
        self.assertNotIn(7, self.main.camera_threads)

    def test_ptz_opt_out_and_other_models(self):
        self.main.cameras[0]['ptz'] = False
        self.select([7])
        self.assertIsNone(self.main.lens_views[(7, 'lower')].ptz_pad)
        self.main.cameras[0]['model'] = 'other'
        self.select([7])
        self.assertFalse(self.main.lens_views)
        self.assertIn(7, self.main.multi_view_labels)

    def test_disconnect_updates_both_views_without_new_thread(self):
        self.select([7])
        thread = self.main.camera_threads[7]
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        self.main.update_camera_status(False, 7, 'Reconnecting')
        self.assertTrue(all(w.frame is None for w in self.main.lens_views.values()))
        self.assertIs(self.main.camera_threads[7], thread)

    def test_full_frame_reaches_preview_and_detection_unchanged(self):
        self.select([7])
        self.main.cameras[0]['detection_enabled'] = True
        self.main.detection_worker = MagicMock()
        frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.update_camera_frame(frame, 7)
        self.assertIs(self.main.camera_widgets[7].last_frame, frame)
        self.assertIs(self.main.detection_worker.submit_frame.call_args.args[2], frame)
        self.assertEqual(frame.shape, (200, 160, 3))

    def test_disconnect_does_not_restore_stale_cached_frame(self):
        self.select([7])
        widget = self.main.camera_widgets[7]
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        self.main.update_camera_status(False, 7, 'Reconnecting')
        self.assertIsNone(widget.last_frame)
        self.select([7])
        self.assertTrue(all(w.frame is None for w in self.main.lens_views.values()))

    def test_start_ignores_cached_frame_from_previous_session(self):
        self.select([7])
        widget = self.main.camera_widgets[7]
        widget.last_frame = np.zeros((200, 160, 3), dtype=np.uint8)
        with patch('main_window.CameraThread'), patch.object(self.main, '_prebuffer_seconds', return_value=0):
            self.main._start_camera_thread(CAMERA)
        self.assertTrue(all(w.frame is None for w in self.main.lens_views.values()))

    def test_click_reopens_tiles_in_multi_view_without_extra_thread(self):
        self.select([7, 8])
        with patch('main_window.CameraThread') as factory:
            self.main.select_camera(7)
            factory.assert_not_called()
        self.assertEqual(len(self.main.lens_views), 2)

    def test_four_cameras_produce_five_tiles_in_main_grid(self):
        self.select([8, 9, 10, 7])
        self.assertEqual(set(self.main.multi_view_labels), {8, 9, 10})
        self.assertEqual(len(self.main.lens_views), 2)
        self.assertEqual(self.main.big_preview_layout.count(), 3)
        self.assertEqual(self.main.big_preview_layout.itemAt(1).layout().itemAt(1).widget(),
                         self.main.lens_views[(7, 'upper')])
        self.assertEqual(self.main.big_preview_layout.itemAt(2).layout().itemAt(0).widget(),
                         self.main.lens_views[(7, 'lower')])
        self.assertTrue(all(not w.isWindow() for w in self.main.lens_views.values()))
        self.assertEqual(len([label for label in self.main.big_preview_container.findChildren(PreviewLabel)
                              if label.isVisible()]), 5)

    def test_double_click_expands_one_half_and_restores_grid_with_zoom_preserved(self):
        self.select([7, 8, 9])
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        top, bottom = (self.main.lens_views[(7, half)] for half in ('upper', 'lower'))
        bottom.zoom(2)
        crop = QRect(bottom.crop_rect)
        top.label.double_clicked.emit(7)
        self.app.processEvents()
        self.assertEqual(self.main.zoomed_lens_key, (7, 'upper'))
        self.assertTrue(top.isVisible())
        self.assertTrue(bottom.isHidden())
        self.assertFalse(self.main.multi_view_labels)
        self.assertEqual(len([label for label in self.main.big_preview_container.findChildren(PreviewLabel)
                              if label.isVisible()]), 1)
        self.assertEqual(self.main.big_preview_layout.count(), 1)
        top.label.double_clicked.emit(7)
        self.app.processEvents()
        self.assertIsNone(self.main.zoomed_lens_key)
        self.assertTrue(bottom.isVisible())
        self.assertEqual(bottom.crop_rect, crop)
        self.assertEqual(set(self.main.multi_view_labels), {8, 9})

    def test_other_camera_expand_restore_keeps_lens_zoom(self):
        self.select([7, 8])
        self.main.update_camera_frame(np.zeros((200, 160, 3), dtype=np.uint8), 7)
        bottom = self.main.lens_views[(7, 'lower')]
        bottom.zoom(2)
        crop = QRect(bottom.crop_rect)
        self.main._on_big_preview_label_double_clicked(8)
        self.assertTrue(bottom.isHidden())
        self.main._on_big_preview_label_double_clicked(8)
        self.assertTrue(bottom.isVisible())
        self.assertEqual(bottom.crop_rect, crop)

    def test_single_camera_selection_and_restore_show_two_embedded_views(self):
        self.main.select_camera(7)
        self.assertEqual(len(self.main.lens_views), 2)
        self.assertTrue(all(v.isVisible() for v in self.main.lens_views.values()))
        with patch('main_window.QTimer.singleShot'):
            self.main._restore_preview_state()
        self.assertEqual(len(self.main.lens_views), 2)
        self.main.select_camera(8)
        self.assertFalse(self.main.lens_views)
        self.assertIn(8, self.main.multi_view_labels)

    def test_closing_both_halves_deselects_camera_without_stopping_stream(self):
        self.main.on_camera_selection_changed(7, True)
        self.main.multi_view_close_buttons[(7, 'upper')][1].click()
        self.main.multi_view_close_buttons[(7, 'lower')][1].click()
        self.assertNotIn(7, self.main.selected_camera_ids)
        self.assertFalse(self.main.camera_widgets[7].view_checkbox.isChecked())
        self.assertFalse(self.main.lens_views)
        self.main.camera_threads[7].stop.assert_not_called()

    def test_unselected_stream_start_never_opens_views(self):
        with patch('main_window.CameraThread'), patch.object(self.main, '_prebuffer_seconds', return_value=0):
            self.main._start_camera_thread(CAMERA)
        self.assertFalse(self.main.lens_views)

    def test_wheel_zooms_normal_tile_and_double_click_resets(self):
        from PyQt6.QtCore import QPoint
        self.select([8, 9])
        frame = np.zeros((200, 160, 3), dtype=np.uint8)
        self.main.update_camera_frame(frame, 8)
        self.main.update_camera_frame(frame, 9)
        label = self.main.multi_view_labels[8]
        pos = QPointF(label.frame_display_rect().center())
        event = QWheelEvent(pos, pos, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(label, event)
        self.assertIn(8, self.main.preview_crops)
        self.assertNotIn(9, self.main.preview_crops)
        label.double_clicked.emit(8)
        self.assertNotIn(8, self.main.preview_crops)

    def test_lens_tiles_have_only_overlay_close_button(self):
        self.select([7, 8])
        for key in ((7, 'upper'), (7, 'lower')):
            self.assertIn(key, self.main.multi_view_close_buttons)
            label, _btn = self.main.multi_view_close_buttons[key]
            self.assertIs(label, self.main.lens_views[key].label)


if __name__ == '__main__':
    unittest.main()

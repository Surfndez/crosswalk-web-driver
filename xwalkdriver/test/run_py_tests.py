#!/usr/bin/env python
# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""End to end tests for XwalkDriver."""

import base64
import json
import math
import optparse
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib2
import shutil

_THIS_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(1, os.path.join(_THIS_DIR, os.pardir))
sys.path.insert(1, os.path.join(_THIS_DIR, os.pardir, 'client'))
sys.path.insert(1, os.path.join(_THIS_DIR, os.pardir, 'server'))

import xwalk_paths
import xwalkdriver
import unittest_util
import util
import server
from webelement import WebElement
import webserver

_TEST_DATA_DIR = os.path.join(xwalk_paths.GetTestData(), 'xwalkdriver')

if util.IsLinux():
  sys.path.insert(0, os.path.join(xwalk_paths.GetSrc(), 'build', 'android'))
  from pylib import constants
  from pylib import forwarder
  from pylib import valgrind_tools
  from pylib.device import device_utils


_NEGATIVE_FILTER = [
    # https://code.google.com/p/xwalkdriver/issues/detail?id=213
    'XwalkDriverTest.testClickElementInSubFrame',
    # This test is flaky since it uses setTimeout.
    # Re-enable once crbug.com/177511 is fixed and we can remove setTimeout.
    'XwalkDriverTest.testAlert',
    # This test is too flaky on the bots, but seems to run perfectly fine
    # on developer workstations.
    'XwalkDriverTest.testEmulateNetworkConditionsNameSpeed',
    'XwalkDriverTest.testEmulateNetworkConditionsSpeed',
    # crbug.com/469947
    'XwalkDriverTest.testTouchPinch'
]

_VERSION_SPECIFIC_FILTER = {}
_VERSION_SPECIFIC_FILTER['HEAD'] = [
    # https://code.google.com/p/xwalkdriver/issues/detail?id=992
    'XwalkDownloadDirTest.testDownloadDirectoryOverridesExistingPreferences',
]
_VERSION_SPECIFIC_FILTER['37'] = [
    # https://code.google.com/p/xwalkdriver/issues/detail?id=954
    'MobileEmulationCapabilityTest.testClickElement',
    'MobileEmulationCapabilityTest.testHoverOverElement',
    'MobileEmulationCapabilityTest.testSingleTapElement',
]
_VERSION_SPECIFIC_FILTER['36'] = [
    # https://code.google.com/p/xwalkdriver/issues/detail?id=954
    'MobileEmulationCapabilityTest.testClickElement',
    'MobileEmulationCapabilityTest.testHoverOverElement',
    'MobileEmulationCapabilityTest.testSingleTapElement',
]

_OS_SPECIFIC_FILTER = {}
_OS_SPECIFIC_FILTER['win'] = [
    # https://code.google.com/p/xwalkdriver/issues/detail?id=214
    'XwalkDriverTest.testCloseWindow',
    # https://code.google.com/p/xwalkdriver/issues/detail?id=299
    'XwalkLogPathCapabilityTest.testXwalkLogPath',
]
_OS_SPECIFIC_FILTER['linux'] = [
    # Xvfb doesn't support maximization.
    'XwalkDriverTest.testWindowMaximize',
    # https://code.google.com/p/xwalkdriver/issues/detail?id=302
    'XwalkDriverTest.testWindowPosition',
    'XwalkDriverTest.testWindowSize',
]
_OS_SPECIFIC_FILTER['mac'] = [
]

_DESKTOP_NEGATIVE_FILTER = [
    # Desktop doesn't support touch (without --touch-events).
    'XwalkDriverTest.testTouchSingleTapElement',
    'XwalkDriverTest.testTouchDownMoveUpElement',
    'XwalkDriverTest.testTouchScrollElement',
    'XwalkDriverTest.testTouchDoubleTapElement',
    'XwalkDriverTest.testTouchLongPressElement',
    'XwalkDriverTest.testTouchFlickElement',
    'XwalkDriverTest.testTouchPinch',
    'XwalkDriverAndroidTest.*',
]


def _GetDesktopNegativeFilter(version_name):
  filter = _NEGATIVE_FILTER + _DESKTOP_NEGATIVE_FILTER
  os = util.GetPlatformName()
  if os in _OS_SPECIFIC_FILTER:
    filter += _OS_SPECIFIC_FILTER[os]
  if version_name in _VERSION_SPECIFIC_FILTER:
    filter += _VERSION_SPECIFIC_FILTER[version_name]
  return filter

_ANDROID_NEGATIVE_FILTER = {}
_ANDROID_NEGATIVE_FILTER['xwalk'] = (
    _NEGATIVE_FILTER + [
        # TODO(chrisgao): fix hang of tab crash test on android.
        'XwalkDriverTest.testTabCrash',
        # Android doesn't support switches and extensions.
        'XwalkSwitchesCapabilityTest.*',
        'XwalkExtensionsCapabilityTest.*',
        'MobileEmulationCapabilityTest.*',
        'XwalkDownloadDirTest.*',
        # https://crbug.com/274650
        'XwalkDriverTest.testCloseWindow',
        # https://code.google.com/p/xwalkdriver/issues/detail?id=270
        'XwalkDriverTest.testPopups',
        # https://code.google.com/p/xwalkdriver/issues/detail?id=298
        'XwalkDriverTest.testWindowPosition',
        'XwalkDriverTest.testWindowSize',
        'XwalkDriverTest.testWindowMaximize',
        'XwalkLogPathCapabilityTest.testXwalkLogPath',
        'RemoteBrowserTest.*',
        # Don't enable perf testing on Android yet.
        'PerfTest.testSessionStartTime',
        'PerfTest.testSessionStopTime',
        'PerfTest.testColdExecuteScript',
        # https://code.google.com/p/xwalkdriver/issues/detail?id=459
        'XwalkDriverTest.testShouldHandleNewWindowLoadingProperly',
        # Android doesn't support multiple sessions on one device.
        'SessionHandlingTest.testGetSessions',
        # Android doesn't use the xwalk://print dialog.
        'XwalkDriverTest.testCanSwitchToPrintPreviewDialog',
    ]
)
_ANDROID_NEGATIVE_FILTER['xwalk_stable'] = (
    _ANDROID_NEGATIVE_FILTER['xwalk'] + [
        # The stable channel Xwalk for Android does not yet support Synthetic
        # Gesture DevTools commands.
        # TODO(samuong): reenable when it does.
        'XwalkDriverTest.testHasTouchScreen',
        'XwalkDriverTest.testTouchScrollElement',
        'XwalkDriverTest.testTouchDoubleTapElement',
        'XwalkDriverTest.testTouchLongPressElement',
        'XwalkDriverTest.testTouchPinch',
    ])
_ANDROID_NEGATIVE_FILTER['xwalk_beta'] = (
    _ANDROID_NEGATIVE_FILTER['xwalk'] + [
        # The beta channel Xwalk for Android does not yet support Synthetic
        # Gesture DevTools commands.
        # TODO(samuong): reenable when it does.
        'XwalkDriverTest.testHasTouchScreen',
        'XwalkDriverTest.testTouchScrollElement',
        'XwalkDriverTest.testTouchDoubleTapElement',
        'XwalkDriverTest.testTouchLongPressElement',
        'XwalkDriverTest.testTouchPinch',
    ])
_ANDROID_NEGATIVE_FILTER['xwalk_shell'] = (
    _ANDROID_NEGATIVE_FILTER['xwalk'] + [
        # XwalkShell doesn't support multiple tabs.
        'XwalkDriverTest.testGetWindowHandles',
        'XwalkDriverTest.testSwitchToWindow',
        'XwalkDriverTest.testShouldHandleNewWindowLoadingProperly',
    ]
)
_ANDROID_NEGATIVE_FILTER['xwalkdriver_webview_shell'] = (
    _ANDROID_NEGATIVE_FILTER['xwalk_shell'] + [
        # https://code.google.com/p/xwalkdriver/issues/detail?id=913
        'XwalkDriverTest.testXwalkDriverSendLargeData',
        'PerformanceLoggerTest.testPerformanceLogger',
        'XwalkDriverTest.testShadowDom*',
        # WebView doesn't support emulating network conditions.
        'XwalkDriverTest.testEmulateNetworkConditions',
        'XwalkDriverTest.testEmulateNetworkConditionsNameSpeed',
        'XwalkDriverTest.testEmulateNetworkConditionsOffline',
        'XwalkDriverTest.testEmulateNetworkConditionsSpeed',
        'XwalkDriverTest.testEmulateNetworkConditionsName',
        # The WebView shell that we test against (on KitKat) does not yet
        # support Synthetic Gesture DevTools commands.
        # TODO(samuong): reenable when it does.
        'XwalkDriverTest.testHasTouchScreen',
        'XwalkDriverTest.testTouchScrollElement',
        'XwalkDriverTest.testTouchDoubleTapElement',
        'XwalkDriverTest.testTouchLongPressElement',
        'XwalkDriverTest.testTouchPinch',
    ]
)


class XwalkDriverBaseTest(unittest.TestCase):
  """Base class for testing xwalkdriver functionalities."""

  def __init__(self, *args, **kwargs):
    super(XwalkDriverBaseTest, self).__init__(*args, **kwargs)
    self._drivers = []

  def tearDown(self):
    for driver in self._drivers:
      try:
        driver.Quit()
      except:
        pass

  def CreateDriver(self, server_url=None, download_dir=None, **kwargs):
    if server_url is None:
      server_url = _CHROMEDRIVER_SERVER_URL

    android_package = None
    android_activity = None
    android_process = None
    if _ANDROID_PACKAGE_KEY:
      android_package = constants.PACKAGE_INFO[_ANDROID_PACKAGE_KEY].package
      if _ANDROID_PACKAGE_KEY == 'xwalkdriver_webview_shell':
        android_activity = constants.PACKAGE_INFO[_ANDROID_PACKAGE_KEY].activity
        android_process = '%s:main' % android_package

    driver = xwalkdriver.XwalkDriver(server_url,
                                       xwalk_binary=_CHROME_BINARY,
                                       android_package=android_package,
                                       android_activity=android_activity,
                                       android_process=android_process,
                                       download_dir=download_dir,
                                       **kwargs)
    self._drivers += [driver]
    return driver

  def WaitForNewWindow(self, driver, old_handles):
    """Wait for at least one new window to show up in 20 seconds.

    Args:
      old_handles: Handles to all old windows before the new window is added.

    Returns:
      Handle to a new window. None if timeout.
    """
    deadline = time.time() + 20
    while time.time() < deadline:
      new_handles = driver.GetWindowHandles()
      if len(new_handles) > len(old_handles):
        for index, old_handle in enumerate(old_handles):
          self.assertEquals(old_handle, new_handles[index])
        return new_handles[len(old_handles)]
      time.sleep(0.01)
    return None


class XwalkDriverTest(XwalkDriverBaseTest):
  """End to end tests for XwalkDriver."""

  @staticmethod
  def GlobalSetUp():
    XwalkDriverTest._http_server = webserver.WebServer(
        xwalk_paths.GetTestData())
    XwalkDriverTest._sync_server = webserver.SyncWebServer()
    if _ANDROID_PACKAGE_KEY:
      XwalkDriverTest._device = device_utils.DeviceUtils.HealthyDevices()[0]
      http_host_port = XwalkDriverTest._http_server._server.server_port
      sync_host_port = XwalkDriverTest._sync_server._server.server_port
      forwarder.Forwarder.Map(
          [(http_host_port, http_host_port), (sync_host_port, sync_host_port)],
          XwalkDriverTest._device)

  @staticmethod
  def GlobalTearDown():
    if _ANDROID_PACKAGE_KEY:
      forwarder.Forwarder.UnmapAllDevicePorts(XwalkDriverTest._device)
    XwalkDriverTest._http_server.Shutdown()

  @staticmethod
  def GetHttpUrlForFile(file_path):
    return XwalkDriverTest._http_server.GetUrl() + file_path

  def setUp(self):
    self._driver = self.CreateDriver()

  def testStartStop(self):
    pass

  def testLoadUrl(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/empty.html'))

  def testGetCurrentWindowHandle(self):
    self._driver.GetCurrentWindowHandle()

  def testCloseWindow(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/page_test.html'))
    old_handles = self._driver.GetWindowHandles()
    self._driver.FindElement('id', 'link').Click()
    new_window_handle = self.WaitForNewWindow(self._driver, old_handles)
    self.assertNotEqual(None, new_window_handle)
    self._driver.SwitchToWindow(new_window_handle)
    self.assertEquals(new_window_handle, self._driver.GetCurrentWindowHandle())
    self.assertRaises(xwalkdriver.NoSuchElement,
                      self._driver.FindElement, 'id', 'link')
    self._driver.CloseWindow()
    self.assertRaises(xwalkdriver.NoSuchWindow,
                      self._driver.GetCurrentWindowHandle)
    new_handles = self._driver.GetWindowHandles()
    for old_handle in old_handles:
      self.assertTrue(old_handle in new_handles)
    for handle in new_handles:
      self._driver.SwitchToWindow(handle)
      self.assertEquals(handle, self._driver.GetCurrentWindowHandle())
      self._driver.CloseWindow()

  def testGetWindowHandles(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/page_test.html'))
    old_handles = self._driver.GetWindowHandles()
    self._driver.FindElement('id', 'link').Click()
    self.assertNotEqual(None, self.WaitForNewWindow(self._driver, old_handles))

  def testSwitchToWindow(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/page_test.html'))
    self.assertEquals(
        1, self._driver.ExecuteScript('window.name = "oldWindow"; return 1;'))
    window1_handle = self._driver.GetCurrentWindowHandle()
    old_handles = self._driver.GetWindowHandles()
    self._driver.FindElement('id', 'link').Click()
    new_window_handle = self.WaitForNewWindow(self._driver, old_handles)
    self.assertNotEqual(None, new_window_handle)
    self._driver.SwitchToWindow(new_window_handle)
    self.assertEquals(new_window_handle, self._driver.GetCurrentWindowHandle())
    self.assertRaises(xwalkdriver.NoSuchElement,
                      self._driver.FindElement, 'id', 'link')
    self._driver.SwitchToWindow('oldWindow')
    self.assertEquals(window1_handle, self._driver.GetCurrentWindowHandle())

  def testEvaluateScript(self):
    self.assertEquals(1, self._driver.ExecuteScript('return 1'))
    self.assertEquals(None, self._driver.ExecuteScript(''))

  def testEvaluateScriptWithArgs(self):
    script = ('document.body.innerHTML = "<div>b</div><div>c</div>";'
              'return {stuff: document.querySelectorAll("div")};')
    stuff = self._driver.ExecuteScript(script)['stuff']
    script = 'return arguments[0].innerHTML + arguments[1].innerHTML'
    self.assertEquals(
        'bc', self._driver.ExecuteScript(script, stuff[0], stuff[1]))

  def testEvaluateInvalidScript(self):
    self.assertRaises(xwalkdriver.XwalkDriverException,
                      self._driver.ExecuteScript, '{{{')

  def testExecuteAsyncScript(self):
    self._driver.SetTimeout('script', 3000)
    self.assertRaises(
        xwalkdriver.ScriptTimeout,
        self._driver.ExecuteAsyncScript,
        'var callback = arguments[0];'
        'setTimeout(function(){callback(1);}, 10000);')
    self.assertEquals(
        2,
        self._driver.ExecuteAsyncScript(
            'var callback = arguments[0];'
            'setTimeout(function(){callback(2);}, 300);'))

  def testSwitchToFrame(self):
    self._driver.ExecuteScript(
        'var frame = document.createElement("iframe");'
        'frame.id="id";'
        'frame.name="name";'
        'document.body.appendChild(frame);')
    self.assertTrue(self._driver.ExecuteScript('return window.top == window'))
    self._driver.SwitchToFrame('id')
    self.assertTrue(self._driver.ExecuteScript('return window.top != window'))
    self._driver.SwitchToMainFrame()
    self.assertTrue(self._driver.ExecuteScript('return window.top == window'))
    self._driver.SwitchToFrame('name')
    self.assertTrue(self._driver.ExecuteScript('return window.top != window'))
    self._driver.SwitchToMainFrame()
    self.assertTrue(self._driver.ExecuteScript('return window.top == window'))
    self._driver.SwitchToFrameByIndex(0)
    self.assertTrue(self._driver.ExecuteScript('return window.top != window'))
    self._driver.SwitchToMainFrame()
    self.assertTrue(self._driver.ExecuteScript('return window.top == window'))
    self._driver.SwitchToFrame(self._driver.FindElement('tag name', 'iframe'))
    self.assertTrue(self._driver.ExecuteScript('return window.top != window'))

  def testSwitchToParentFrame(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/nested.html'))
    self.assertTrue('One' in self._driver.GetPageSource())
    self._driver.SwitchToFrameByIndex(0)
    self.assertTrue('Two' in self._driver.GetPageSource())
    self._driver.SwitchToFrameByIndex(0)
    self.assertTrue('Three' in self._driver.GetPageSource())
    self._driver.SwitchToParentFrame()
    self.assertTrue('Two' in self._driver.GetPageSource())
    self._driver.SwitchToParentFrame()
    self.assertTrue('One' in self._driver.GetPageSource())

  def testExecuteInRemovedFrame(self):
    self._driver.ExecuteScript(
        'var frame = document.createElement("iframe");'
        'frame.id="id";'
        'frame.name="name";'
        'document.body.appendChild(frame);'
        'window.addEventListener("message",'
        '    function(event) { document.body.removeChild(frame); });')
    self.assertTrue(self._driver.ExecuteScript('return window.top == window'))
    self._driver.SwitchToFrame('id')
    self.assertTrue(self._driver.ExecuteScript('return window.top != window'))
    self._driver.ExecuteScript('parent.postMessage("remove", "*");')
    self.assertTrue(self._driver.ExecuteScript('return window.top == window'))

  def testGetTitle(self):
    script = 'document.title = "title"; return 1;'
    self.assertEquals(1, self._driver.ExecuteScript(script))
    self.assertEquals('title', self._driver.GetTitle())

  def testGetPageSource(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/page_test.html'))
    self.assertTrue('Link to empty.html' in self._driver.GetPageSource())

  def testFindElement(self):
    self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>a</div><div>b</div>";')
    self.assertTrue(
        isinstance(self._driver.FindElement('tag name', 'div'), WebElement))

  def testNoSuchElementExceptionMessage(self):
    self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>a</div><div>b</div>";')
    self.assertRaisesRegexp(xwalkdriver.NoSuchElement,
                            'no such element: Unable '
                            'to locate element: {"method":"tag name",'
                            '"selector":"divine"}',
                            self._driver.FindElement,
                            'tag name','divine')

  def testFindElements(self):
    self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>a</div><div>b</div>";')
    divs = self._driver.FindElements('tag name', 'div')
    self.assertTrue(isinstance(divs, list))
    self.assertEquals(2, len(divs))
    for div in divs:
      self.assertTrue(isinstance(div, WebElement))

  def testFindChildElement(self):
    self._driver.ExecuteScript(
        'document.body.innerHTML = "<div><br><br></div><div><a></a></div>";')
    element = self._driver.FindElement('tag name', 'div')
    self.assertTrue(
        isinstance(element.FindElement('tag name', 'br'), WebElement))

  def testFindChildElements(self):
    self._driver.ExecuteScript(
        'document.body.innerHTML = "<div><br><br></div><div><br></div>";')
    element = self._driver.FindElement('tag name', 'div')
    brs = element.FindElements('tag name', 'br')
    self.assertTrue(isinstance(brs, list))
    self.assertEquals(2, len(brs))
    for br in brs:
      self.assertTrue(isinstance(br, WebElement))

  def testHoverOverElement(self):
    div = self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.addEventListener("mouseover", function() {'
        '  document.body.appendChild(document.createElement("br"));'
        '});'
        'return div;')
    div.HoverOver()
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))

  def testClickElement(self):
    div = self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.addEventListener("click", function() {'
        '  div.innerHTML="new<br>";'
        '});'
        'return div;')
    div.Click()
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))

  def testClickElementInSubFrame(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/frame_test.html'))
    frame = self._driver.FindElement('tag name', 'iframe')
    self._driver.SwitchToFrame(frame)
    # Test clicking element in the sub frame.
    self.testClickElement()

  def testClearElement(self):
    text = self._driver.ExecuteScript(
        'document.body.innerHTML = \'<input type="text" value="abc">\';'
        'return document.getElementsByTagName("input")[0];')
    value = self._driver.ExecuteScript('return arguments[0].value;', text)
    self.assertEquals('abc', value)
    text.Clear()
    value = self._driver.ExecuteScript('return arguments[0].value;', text)
    self.assertEquals('', value)

  def testSendKeysToElement(self):
    text = self._driver.ExecuteScript(
        'document.body.innerHTML = \'<input type="text">\';'
        'var input = document.getElementsByTagName("input")[0];'
        'input.addEventListener("change", function() {'
        '  document.body.appendChild(document.createElement("br"));'
        '});'
        'return input;')
    text.SendKeys('0123456789+-*/ Hi')
    text.SendKeys(', there!')
    value = self._driver.ExecuteScript('return arguments[0].value;', text)
    self.assertEquals('0123456789+-*/ Hi, there!', value)

  def testGetCurrentUrl(self):
    self.assertEquals('data:,', self._driver.GetCurrentUrl())

  def testGoBackAndGoForward(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/empty.html'))
    self._driver.GoBack()
    self._driver.GoForward()

  def testDontGoBackOrGoForward(self):
    self.assertEquals('data:,', self._driver.GetCurrentUrl())
    self._driver.GoBack()
    self.assertEquals('data:,', self._driver.GetCurrentUrl())
    self._driver.GoForward()
    self.assertEquals('data:,', self._driver.GetCurrentUrl())

  def testRefresh(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/empty.html'))
    self._driver.Refresh()

  def testMouseMoveTo(self):
    div = self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.style["width"] = "100px";'
        'div.style["height"] = "100px";'
        'div.addEventListener("mouseover", function() {'
        '  var div = document.getElementsByTagName("div")[0];'
        '  div.innerHTML="new<br>";'
        '});'
        'return div;')
    self._driver.MouseMoveTo(div, 10, 10)
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))

  def testMoveToElementAndClick(self):
    # This page gets rendered differently depending on which platform the test
    # is running on, and what window size is being used. So we need to do some
    # sanity checks to make sure that the <a> element is split across two lines
    # of text.
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/multiline.html'))

    # Check that link element spans two lines and that the first ClientRect is
    # above the second.
    link = self._driver.FindElements('tag name', 'a')[0]
    client_rects = self._driver.ExecuteScript(
        'return arguments[0].getClientRects();', link)
    self.assertEquals(2, len(client_rects))
    self.assertTrue(client_rects[0]['bottom'] <= client_rects[1]['top'])

    # Check that the center of the link's bounding ClientRect is outside the
    # element.
    bounding_client_rect = self._driver.ExecuteScript(
        'return arguments[0].getBoundingClientRect();', link)
    center = bounding_client_rect['left'] + bounding_client_rect['width'] / 2
    self.assertTrue(client_rects[1]['right'] < center)
    self.assertTrue(center < client_rects[0]['left'])

    self._driver.MouseMoveTo(link)
    self._driver.MouseClick()
    self.assertTrue(self._driver.GetCurrentUrl().endswith('#top'))

  def testMouseClick(self):
    div = self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.style["width"] = "100px";'
        'div.style["height"] = "100px";'
        'div.addEventListener("click", function() {'
        '  var div = document.getElementsByTagName("div")[0];'
        '  div.innerHTML="new<br>";'
        '});'
        'return div;')
    self._driver.MouseMoveTo(div)
    self._driver.MouseClick()
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))

  def testMouseButtonDownAndUp(self):
    self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.style["width"] = "100px";'
        'div.style["height"] = "100px";'
        'div.addEventListener("mousedown", function() {'
        '  var div = document.getElementsByTagName("div")[0];'
        '  div.innerHTML="new1<br>";'
        '});'
        'div.addEventListener("mouseup", function() {'
        '  var div = document.getElementsByTagName("div")[0];'
        '  div.innerHTML="new2<a></a>";'
        '});')
    self._driver.MouseMoveTo(None, 50, 50)
    self._driver.MouseButtonDown()
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))
    self._driver.MouseButtonUp()
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'a')))

  def testMouseDoubleClick(self):
    div = self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.style["width"] = "100px";'
        'div.style["height"] = "100px";'
        'div.addEventListener("dblclick", function() {'
        '  var div = document.getElementsByTagName("div")[0];'
        '  div.innerHTML="new<br>";'
        '});'
        'return div;')
    self._driver.MouseMoveTo(div, 1, 1)
    self._driver.MouseDoubleClick()
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))

  def testAlert(self):
    self.assertFalse(self._driver.IsAlertOpen())
    self._driver.ExecuteScript(
        'window.setTimeout('
        '    function() { window.confirmed = confirm(\'HI\'); },'
        '    0);')
    self.assertTrue(self._driver.IsAlertOpen())
    self.assertEquals('HI', self._driver.GetAlertMessage())
    self._driver.HandleAlert(False)
    self.assertFalse(self._driver.IsAlertOpen())
    self.assertEquals(False,
                      self._driver.ExecuteScript('return window.confirmed'))

  def testShouldHandleNewWindowLoadingProperly(self):
    """Tests that XwalkDriver determines loading correctly for new windows."""
    self._http_server.SetDataForPath(
        '/newwindow',
        """
        <html>
        <body>
        <a href='%s' target='_blank'>new window/tab</a>
        </body>
        </html>""" % self._sync_server.GetUrl())
    self._driver.Load(self._http_server.GetUrl() + '/newwindow')
    old_windows = self._driver.GetWindowHandles()
    self._driver.FindElement('tagName', 'a').Click()
    new_window = self.WaitForNewWindow(self._driver, old_windows)
    self.assertNotEqual(None, new_window)

    self.assertFalse(self._driver.IsLoading())
    self._driver.SwitchToWindow(new_window)
    self.assertTrue(self._driver.IsLoading())
    self._sync_server.RespondWithContent('<html>new window</html>')
    self._driver.ExecuteScript('return 1')  # Shouldn't hang.

  def testPopups(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/empty.html'))
    old_handles = self._driver.GetWindowHandles()
    self._driver.ExecuteScript('window.open("about:blank")')
    new_window_handle = self.WaitForNewWindow(self._driver, old_handles)
    self.assertNotEqual(None, new_window_handle)

  def testNoSuchFrame(self):
    self.assertRaises(xwalkdriver.NoSuchFrame,
                      self._driver.SwitchToFrame, 'nosuchframe')
    self.assertRaises(xwalkdriver.NoSuchFrame,
                      self._driver.SwitchToFrame,
                      self._driver.FindElement('tagName', 'body'))

  def testWindowPosition(self):
    position = self._driver.GetWindowPosition()
    self._driver.SetWindowPosition(position[0], position[1])
    self.assertEquals(position, self._driver.GetWindowPosition())

    # Resize so the window isn't moved offscreen.
    # See https://code.google.com/p/xwalkdriver/issues/detail?id=297.
    self._driver.SetWindowSize(300, 300)

    self._driver.SetWindowPosition(100, 200)
    self.assertEquals([100, 200], self._driver.GetWindowPosition())

  def testWindowSize(self):
    size = self._driver.GetWindowSize()
    self._driver.SetWindowSize(size[0], size[1])
    self.assertEquals(size, self._driver.GetWindowSize())

    self._driver.SetWindowSize(600, 400)
    self.assertEquals([600, 400], self._driver.GetWindowSize())

  def testWindowMaximize(self):
    self._driver.SetWindowPosition(100, 200)
    self._driver.SetWindowSize(600, 400)
    self._driver.MaximizeWindow()

    self.assertNotEqual([100, 200], self._driver.GetWindowPosition())
    self.assertNotEqual([600, 400], self._driver.GetWindowSize())
    # Set size first so that the window isn't moved offscreen.
    # See https://code.google.com/p/xwalkdriver/issues/detail?id=297.
    self._driver.SetWindowSize(600, 400)
    self._driver.SetWindowPosition(100, 200)
    self.assertEquals([100, 200], self._driver.GetWindowPosition())
    self.assertEquals([600, 400], self._driver.GetWindowSize())

  def testConsoleLogSources(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/console_log.html'))
    logs = self._driver.GetLog('browser')

    self.assertEqual('network', logs[0]['source'])
    self.assertTrue('nonexistent.png' in logs[0]['message'])
    self.assertTrue('404' in logs[0]['message'])

    self.assertEqual('javascript', logs[1]['source'])
    self.assertTrue('TypeError' in logs[1]['message'])

    # Sometimes, we also get an error for a missing favicon.
    if len(logs) > 2:
      self.assertEqual('network', logs[2]['source'])
      self.assertTrue('favicon.ico' in logs[2]['message'])
      self.assertTrue('404' in logs[2]['message'])
      self.assertEqual(3, len(logs))
    else:
      self.assertEqual(2, len(logs))

  def testAutoReporting(self):
    self.assertFalse(self._driver.IsAutoReporting())
    self._driver.SetAutoReporting(True)
    self.assertTrue(self._driver.IsAutoReporting())
    url = self.GetHttpUrlForFile('/xwalkdriver/console_log.html')
    self.assertRaisesRegexp(xwalkdriver.UnknownError,
                            '.*(404|Failed to load resource).*',
                            self._driver.Load,
                            url)

  def testContextMenuEventFired(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/context_menu.html'))
    self._driver.MouseMoveTo(self._driver.FindElement('tagName', 'div'))
    self._driver.MouseClick(2)
    self.assertTrue(self._driver.ExecuteScript('return success'))

  def testHasFocusOnStartup(self):
    # Some pages (about:blank) cause Xwalk to put the focus in URL bar.
    # This breaks tests depending on focus.
    self.assertTrue(self._driver.ExecuteScript('return document.hasFocus()'))

  def testTabCrash(self):
    # If a tab is crashed, the session will be deleted.
    # When 31 is released, will reload the tab instead.
    # https://code.google.com/p/xwalkdriver/issues/detail?id=547
    self.assertRaises(xwalkdriver.UnknownError,
                      self._driver.Load, 'xwalk://crash')
    self.assertRaises(xwalkdriver.NoSuchSession,
                      self._driver.GetCurrentUrl)

  def testDoesntHangOnDebugger(self):
    self._driver.ExecuteScript('debugger;')

  def testMobileEmulationDisabledByDefault(self):
    self.assertFalse(self._driver.capabilities['mobileEmulationEnabled'])

  def testXwalkDriverSendLargeData(self):
    script = 's = ""; for (i = 0; i < 10e6; i++) s += "0"; return s;'
    lots_of_data = self._driver.ExecuteScript(script)
    self.assertEquals('0'.zfill(int(10e6)), lots_of_data)

  def testEmulateNetworkConditions(self):
    # Network conditions must be set before it can be retrieved.
    self.assertRaises(xwalkdriver.UnknownError,
                      self._driver.GetNetworkConditions)

    # DSL: 2Mbps throughput, 5ms RTT
    latency = 5
    throughput = 2048 * 1024
    self._driver.SetNetworkConditions(latency, throughput, throughput)

    network = self._driver.GetNetworkConditions()
    self.assertEquals(latency, network['latency']);
    self.assertEquals(throughput, network['download_throughput']);
    self.assertEquals(throughput, network['upload_throughput']);
    self.assertEquals(False, network['offline']);

    # Network Conditions again cannot be retrieved after they've been deleted.
    self._driver.DeleteNetworkConditions()
    self.assertRaises(xwalkdriver.UnknownError,
                      self._driver.GetNetworkConditions)

  def testEmulateNetworkConditionsName(self):
    # DSL: 2Mbps throughput, 5ms RTT
    #latency = 5
    #throughput = 2048 * 1024
    self._driver.SetNetworkConditionsName('DSL')

    network = self._driver.GetNetworkConditions()
    self.assertEquals(5, network['latency']);
    self.assertEquals(2048*1024, network['download_throughput']);
    self.assertEquals(2048*1024, network['upload_throughput']);
    self.assertEquals(False, network['offline']);

  def testEmulateNetworkConditionsSpeed(self):
    # Warm up the browser.
    self._http_server.SetDataForPath(
        '/', "<html><body>blank</body></html>")
    self._driver.Load(self._http_server.GetUrl() + '/')

    # DSL: 2Mbps throughput, 5ms RTT
    latency = 5
    throughput_kbps = 2048
    throughput = throughput_kbps * 1024
    self._driver.SetNetworkConditions(latency, throughput, throughput)

    _32_bytes = " 0 1 2 3 4 5 6 7 8 9 A B C D E F"
    _1_megabyte = _32_bytes * 32768
    self._http_server.SetDataForPath(
        '/1MB',
        "<html><body>%s</body></html>" % _1_megabyte)
    start = time.time()
    self._driver.Load(self._http_server.GetUrl() + '/1MB')
    finish = time.time()
    duration = finish - start
    actual_throughput_kbps = 1024 / duration
    self.assertLessEqual(actual_throughput_kbps, throughput_kbps * 1.5)
    self.assertGreaterEqual(actual_throughput_kbps, throughput_kbps / 1.5)

  def testEmulateNetworkConditionsNameSpeed(self):
    # Warm up the browser.
    self._http_server.SetDataForPath(
        '/', "<html><body>blank</body></html>")
    self._driver.Load(self._http_server.GetUrl() + '/')

    # DSL: 2Mbps throughput, 5ms RTT
    throughput_kbps = 2048
    throughput = throughput_kbps * 1024
    self._driver.SetNetworkConditionsName('DSL')

    _32_bytes = " 0 1 2 3 4 5 6 7 8 9 A B C D E F"
    _1_megabyte = _32_bytes * 32768
    self._http_server.SetDataForPath(
        '/1MB',
        "<html><body>%s</body></html>" % _1_megabyte)
    start = time.time()
    self._driver.Load(self._http_server.GetUrl() + '/1MB')
    finish = time.time()
    duration = finish - start
    actual_throughput_kbps = 1024 / duration
    self.assertLessEqual(actual_throughput_kbps, throughput_kbps * 1.5)
    self.assertGreaterEqual(actual_throughput_kbps, throughput_kbps / 1.5)

  def testEmulateNetworkConditionsOffline(self):
    # A workaround for crbug.com/177511; when setting offline, the throughputs
    # must be 0.
    self._driver.SetNetworkConditions(0, 0, 0, offline=True)
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/page_test.html'))
    self.assertIn('is not available', self._driver.GetTitle())

  def testShadowDomFindElementWithSlashDeep(self):
    """Checks that xwalkdriver can find elements in a shadow DOM using /deep/
    css selectors."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    self.assertTrue(self._driver.FindElement("css", "* /deep/ #olderTextBox"))

  def testShadowDomFindChildElement(self):
    """Checks that xwalkdriver can find child elements from a shadow DOM
    element."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderChildDiv")
    self.assertTrue(elem.FindElement("id", "olderTextBox"))

  def testShadowDomFindElementFailsFromRootWithoutSlashDeep(self):
    """Checks that xwalkdriver can't find elements in a shadow DOM without
    /deep/."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    # can't find element from the root without /deep/
    with self.assertRaises(xwalkdriver.NoSuchElement):
      self._driver.FindElement("id", "#olderTextBox")

  def testShadowDomFindElementFailsBetweenShadowRoots(self):
    """Checks that xwalkdriver can't find elements in other shadow DOM
    trees."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #youngerChildDiv")
    with self.assertRaises(xwalkdriver.NoSuchElement):
      elem.FindElement("id", "#olderTextBox")

  def testShadowDomText(self):
    """Checks that xwalkdriver can find extract the text from a shadow DOM
    element."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderHeading")
    self.assertEqual("Older Child", elem.GetText())

  def testShadowDomSendKeys(self):
    """Checks that xwalkdriver can call SendKeys on a shadow DOM element."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderTextBox")
    elem.SendKeys("bar")
    self.assertEqual("foobar", self._driver.ExecuteScript(
        'return document.querySelector("* /deep/ #olderTextBox").value;'))

  def testShadowDomClear(self):
    """Checks that xwalkdriver can call Clear on a shadow DOM element."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderTextBox")
    elem.Clear()
    self.assertEqual("", self._driver.ExecuteScript(
        'return document.querySelector("* /deep/ #olderTextBox").value;'))

  def testShadowDomClick(self):
    """Checks that xwalkdriver can call Click on an element in a shadow DOM."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderButton")
    elem.Click()
    # the button's onClicked handler changes the text box's value
    self.assertEqual("Button Was Clicked", self._driver.ExecuteScript(
        'return document.querySelector("* /deep/ #olderTextBox").value;'))

  def testShadowDomHover(self):
    """Checks that xwalkdriver can call HoverOver on an element in a
    shadow DOM."""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderButton")
    elem.HoverOver()
    # the button's onMouseOver handler changes the text box's value
    self.assertEqual("Button Was Hovered Over", self._driver.ExecuteScript(
        'return document.querySelector("* /deep/ #olderTextBox").value;'))

  def testShadowDomStaleReference(self):
    """Checks that trying to manipulate shadow DOM elements that are detached
    from the document raises a StaleElementReference exception"""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderButton")
    self._driver.ExecuteScript(
        'document.querySelector("#outerDiv").innerHTML="<div/>";')
    with self.assertRaises(xwalkdriver.StaleElementReference):
      elem.Click()

  def testShadowDomDisplayed(self):
    """Checks that trying to manipulate shadow DOM elements that are detached
    from the document raises a StaleElementReference exception"""
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/shadow_dom_test.html'))
    elem = self._driver.FindElement("css", "* /deep/ #olderButton")
    self.assertTrue(elem.IsDisplayed())
    self._driver.ExecuteScript(
        'document.querySelector("#outerDiv").style.display="None";')
    self.assertFalse(elem.IsDisplayed())

  def testTouchSingleTapElement(self):
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/touch_action_tests.html'))
    events = self._driver.FindElement('id', 'events')
    events.SingleTap()
    self.assertEquals('events: touchstart touchend', events.GetText())

  def testTouchDownMoveUpElement(self):
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/touch_action_tests.html'))
    events = self._driver.FindElement('id', 'events')
    location = events.GetLocation()
    self._driver.TouchDown(location['x'], location['y'])
    self.assertEquals('events: touchstart', events.GetText())
    self._driver.TouchMove(location['x'] + 1, location['y'] + 1)
    self.assertEquals('events: touchstart touchmove', events.GetText())
    self._driver.TouchUp(location['x'] + 1, location['y'] + 1)
    self.assertEquals('events: touchstart touchmove touchend', events.GetText())

  def testTouchScrollElement(self):
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/touch_action_tests.html'))
    scroll_left = 'return document.body.scrollLeft;'
    scroll_top = 'return document.body.scrollTop;'
    self.assertEquals(0, self._driver.ExecuteScript(scroll_left))
    self.assertEquals(0, self._driver.ExecuteScript(scroll_top))
    events = self._driver.FindElement('id', 'events')
    self._driver.TouchScroll(events, 47, 53)
    self.assertEquals(47, self._driver.ExecuteScript(scroll_left))
    self.assertEquals(53, self._driver.ExecuteScript(scroll_top))

  def testTouchDoubleTapElement(self):
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/touch_action_tests.html'))
    events = self._driver.FindElement('id', 'events')
    events.DoubleTap()
    self.assertEquals('events: touchstart touchend touchstart touchend',
        events.GetText())

  def testTouchLongPressElement(self):
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/touch_action_tests.html'))
    events = self._driver.FindElement('id', 'events')
    events.LongPress()
    self.assertEquals('events: touchstart touchcancel', events.GetText())

  def testTouchFlickElement(self):
    dx = 3
    dy = 4
    speed = 5
    flickTouchEventsPerSecond = 30
    moveEvents = int(
        math.sqrt(dx * dx + dy * dy) * flickTouchEventsPerSecond / speed)
    div = self._driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.addEventListener("touchstart", function() {'
        '  div.innerHTML = "preMove0";'
        '});'
        'div.addEventListener("touchmove", function() {'
        '  res = div.innerHTML.match(/preMove(\d+)/);'
        '  if (res != null) {'
        '    div.innerHTML = "preMove" + (parseInt(res[1], 10) + 1);'
        '  }'
        '});'
        'div.addEventListener("touchend", function() {'
        '  if (div.innerHTML == "preMove' + str(moveEvents) + '") {'
        '    div.innerHTML = "new<br>";'
        '  }'
        '});'
        'return div;')
    self._driver.TouchFlick(div, dx, dy, speed)
    self.assertEquals(1, len(self._driver.FindElements('tag name', 'br')))

  def testTouchPinch(self):
    self._driver.Load(self.GetHttpUrlForFile(
        '/xwalkdriver/touch_action_tests.html'))
    width_before_pinch = self._driver.ExecuteScript('return window.innerWidth;')
    height_before_pinch = self._driver.ExecuteScript(
        'return window.innerHeight;')
    self._driver.TouchPinch(width_before_pinch / 2,
                            height_before_pinch / 2,
                            2.0)
    width_after_pinch = self._driver.ExecuteScript('return window.innerWidth;')
    self.assertAlmostEqual(2.0, float(width_before_pinch) / width_after_pinch)

  def testBrowserDoesntSupportSyntheticGestures(self):
    # Current versions of stable and beta channel Xwalk for Android do not
    # support synthetic gesture commands in DevTools, so touch action tests have
    # been disabled for xwalk_stable and xwalk_beta.
    # TODO(samuong): when this test starts failing, re-enable touch tests and
    # delete this test.
    if _ANDROID_PACKAGE_KEY:
      packages = ['xwalk_stable', 'xwalk_beta', 'xwalkdriver_webview_shell']
      if _ANDROID_PACKAGE_KEY in packages:
        self.assertFalse(self._driver.capabilities['hasTouchScreen'])

  def testHasTouchScreen(self):
    self.assertIn('hasTouchScreen', self._driver.capabilities)
    if _ANDROID_PACKAGE_KEY:
      self.assertTrue(self._driver.capabilities['hasTouchScreen'])
    else:
      self.assertFalse(self._driver.capabilities['hasTouchScreen'])

  def testSwitchesToTopFrameAfterNavigation(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/outer.html'))
    frame = self._driver.FindElement('tag name', 'iframe')
    self._driver.SwitchToFrame(frame)
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/outer.html'))
    p = self._driver.FindElement('tag name', 'p')
    self.assertEquals('Two', p.GetText())

  def testSwitchesToTopFrameAfterRefresh(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/outer.html'))
    frame = self._driver.FindElement('tag name', 'iframe')
    self._driver.SwitchToFrame(frame)
    self._driver.Refresh()
    p = self._driver.FindElement('tag name', 'p')
    self.assertEquals('Two', p.GetText())

  def testSwitchesToTopFrameAfterGoingBack(self):
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/outer.html'))
    frame = self._driver.FindElement('tag name', 'iframe')
    self._driver.SwitchToFrame(frame)
    self._driver.Load(self.GetHttpUrlForFile('/xwalkdriver/inner.html'))
    self._driver.GoBack()
    p = self._driver.FindElement('tag name', 'p')
    self.assertEquals('Two', p.GetText())

  def testCanSwitchToPrintPreviewDialog(self):
    old_handles = self._driver.GetWindowHandles()
    self.assertEquals(1, len(old_handles))
    self._driver.ExecuteScript('setTimeout(function(){window.print();}, 0);')
    new_window_handle = self.WaitForNewWindow(self._driver, old_handles)
    self.assertNotEqual(None, new_window_handle)
    self._driver.SwitchToWindow(new_window_handle)
    self.assertEquals('xwalk://print/', self._driver.GetCurrentUrl())


class XwalkDriverAndroidTest(XwalkDriverBaseTest):
  """End to end tests for Android-specific tests."""

  def testLatestAndroidAppInstalled(self):
    if ('stable' not in _ANDROID_PACKAGE_KEY and
        'beta' not in _ANDROID_PACKAGE_KEY):
      return

    self._driver = self.CreateDriver()

    try:
      omaha_list = json.loads(
          urllib2.urlopen('http://omahaproxy.appspot.com/all.json').read())
      for l in omaha_list:
        if l['os'] != 'android':
          continue
        for v in l['versions']:
          if (('stable' in v['channel'] and 'stable' in _ANDROID_PACKAGE_KEY) or
              ('beta' in v['channel'] and 'beta' in _ANDROID_PACKAGE_KEY)):
            omaha = map(int, v['version'].split('.'))
            device = map(int, self._driver.capabilities['version'].split('.'))
            self.assertTrue(omaha <= device)
            return
      raise RuntimeError('Malformed omaha JSON')
    except urllib2.URLError as e:
      print 'Unable to fetch current version info from omahaproxy (%s)' % e

  def testDeviceManagement(self):
    self._drivers = [self.CreateDriver()
                     for _ in device_utils.DeviceUtils.HealthyDevices()]
    self.assertRaises(xwalkdriver.UnknownError, self.CreateDriver)
    self._drivers[0].Quit()
    self._drivers[0] = self.CreateDriver()

class XwalkDownloadDirTest(XwalkDriverBaseTest):

  def __init__(self, *args, **kwargs):
    super(XwalkDownloadDirTest, self).__init__(*args, **kwargs)
    self._temp_dirs = []

  def CreateTempDir(self):
    temp_dir = tempfile.mkdtemp()
    self._temp_dirs.append(temp_dir)
    return temp_dir

  def tearDown(self):
    # Call the superclass tearDown() method before deleting temp dirs, so that
    # Xwalk has a chance to exit before its user data dir is blown away from
    # underneath it.
    super(XwalkDownloadDirTest, self).tearDown()
    for temp_dir in self._temp_dirs:
      shutil.rmtree(temp_dir)

  def testFileDownload(self):
    download_dir = self.CreateTempDir()
    download_name = os.path.join(download_dir, 'a_red_dot.png')
    driver = self.CreateDriver(download_dir=download_dir)
    driver.Load(XwalkDriverTest.GetHttpUrlForFile(
        '/xwalkdriver/download.html'))
    driver.FindElement('id', 'red-dot').Click()
    deadline = time.time() + 60
    while True:
      time.sleep(0.1)
      if os.path.isfile(download_name) or time.time() > deadline:
        break
    self.assertTrue(os.path.isfile(download_name), "Failed to download file!")

  def testDownloadDirectoryOverridesExistingPreferences(self):
    user_data_dir = self.CreateTempDir()
    download_dir = self.CreateTempDir()
    sub_dir = os.path.join(user_data_dir, 'Default')
    os.mkdir(sub_dir)
    prefs_file_path = os.path.join(sub_dir, 'Preferences')

    prefs = {
      'test': 'this should not be changed',
      'download': {
        'default_directory': '/old/download/directory'
      }
    }

    with open(prefs_file_path, 'w') as f:
      json.dump(prefs, f)

    driver = self.CreateDriver(
        xwalk_switches=['user-data-dir=' + user_data_dir],
        download_dir=download_dir)

    with open(prefs_file_path) as f:
      prefs = json.load(f)

    self.assertEqual('this should not be changed', prefs['test'])
    download = prefs['download']
    self.assertEqual(download['default_directory'], download_dir)

class XwalkSwitchesCapabilityTest(XwalkDriverBaseTest):
  """Tests that xwalkdriver properly processes xwalkOptions.args capabilities.

  Makes sure the switches are passed to Xwalk.
  """

  def testSwitchWithoutArgument(self):
    """Tests that switch --dom-automation can be passed to Xwalk.

    Unless --dom-automation is specified, window.domAutomationController
    is undefined.
    """
    driver = self.CreateDriver(xwalk_switches=['dom-automation'])
    self.assertNotEqual(
        None,
        driver.ExecuteScript('return window.domAutomationController'))


class XwalkExtensionsCapabilityTest(XwalkDriverBaseTest):
  """Tests that xwalkdriver properly processes xwalkOptions.extensions."""

  def _PackExtension(self, ext_path):
    return base64.b64encode(open(ext_path, 'rb').read())

  def testExtensionsInstall(self):
    """Checks that xwalkdriver can take the extensions in crx format."""
    crx_1 = os.path.join(_TEST_DATA_DIR, 'ext_test_1.crx')
    crx_2 = os.path.join(_TEST_DATA_DIR, 'ext_test_2.crx')
    self.CreateDriver(xwalk_extensions=[self._PackExtension(crx_1),
                                         self._PackExtension(crx_2)])

  def testExtensionsInstallZip(self):
    """Checks that xwalkdriver can take the extensions in zip format."""
    zip_1 = os.path.join(_TEST_DATA_DIR, 'ext_test_1.zip')
    self.CreateDriver(xwalk_extensions=[self._PackExtension(zip_1)])

  def testWaitsForExtensionToLoad(self):
    did_load_event = threading.Event()
    server = webserver.SyncWebServer()
    def RunServer():
      time.sleep(5)
      server.RespondWithContent('<html>iframe</html>')
      did_load_event.set()

    thread = threading.Thread(target=RunServer)
    thread.daemon = True
    thread.start()
    crx = os.path.join(_TEST_DATA_DIR, 'ext_slow_loader.crx')
    driver = self.CreateDriver(
        xwalk_switches=['user-agent=' + server.GetUrl()],
        xwalk_extensions=[self._PackExtension(crx)])
    self.assertTrue(did_load_event.is_set())

  def testCanLaunchApp(self):
    app_path = os.path.join(_TEST_DATA_DIR, 'test_app')
    driver = self.CreateDriver(xwalk_switches=['load-extension=%s' % app_path])
    old_handles = driver.GetWindowHandles()
    self.assertEqual(1, len(old_handles))
    driver.LaunchApp('gegjcdcfeiojglhifpmibkadodekakpc')
    new_window_handle = self.WaitForNewWindow(driver, old_handles)
    current_window_handle = driver.GetCurrentWindowHandle()
    self.assertEqual(new_window_handle, current_window_handle,
        "focus should switch to the window that the app launches in")
    body_element = driver.FindElement('tag name', 'body')
    self.assertEqual('It works!', body_element.GetText())


class XwalkLogPathCapabilityTest(XwalkDriverBaseTest):
  """Tests that xwalkdriver properly processes xwalkOptions.logPath."""

  LOG_MESSAGE = 'Welcome to XwalkLogPathCapabilityTest!'

  def testXwalkLogPath(self):
    """Checks that user can specify the path of the xwalk log.

    Verifies that a log message is written into the specified log file.
    """
    tmp_log_path = tempfile.NamedTemporaryFile()
    driver = self.CreateDriver(xwalk_log_path=tmp_log_path.name)
    driver.ExecuteScript('console.info("%s")' % self.LOG_MESSAGE)
    driver.Quit()
    self.assertTrue(self.LOG_MESSAGE in open(tmp_log_path.name).read())


class MobileEmulationCapabilityTest(XwalkDriverBaseTest):
  """Tests that XwalkDriver processes xwalkOptions.mobileEmulation.

  Makes sure the device metrics are overridden in DevTools and user agent is
  overridden in Xwalk.
  """

  @staticmethod
  def GlobalSetUp():
    def respondWithUserAgentString(request):
      return """
        <html>
        <body>%s</body>
        </html>""" % request.GetHeader('User-Agent')

    def respondWithUserAgentStringUseDeviceWidth(request):
      return """
        <html>
        <head>
        <meta name="viewport" content="width=device-width,minimum-scale=1.0">
        </head>
        <body>%s</body>
        </html>""" % request.GetHeader('User-Agent')

    MobileEmulationCapabilityTest._http_server = webserver.WebServer(
        xwalk_paths.GetTestData())
    MobileEmulationCapabilityTest._http_server.SetCallbackForPath(
        '/userAgent', respondWithUserAgentString)
    MobileEmulationCapabilityTest._http_server.SetCallbackForPath(
        '/userAgentUseDeviceWidth', respondWithUserAgentStringUseDeviceWidth)

  @staticmethod
  def GlobalTearDown():
    MobileEmulationCapabilityTest._http_server.Shutdown()

  def testDeviceMetricsWithStandardWidth(self):
    driver = self.CreateDriver(
        mobile_emulation = {
            'deviceMetrics': {'width': 360, 'height': 640, 'pixelRatio': 3},
            'userAgent': 'Mozilla/5.0 (Linux; Android 4.2.1; en-us; Nexus 5 Bui'
                         'ld/JOP40D) AppleWebKit/535.19 (KHTML, like Gecko) Chr'
                         'ome/18.0.1025.166 Mobile Safari/535.19'
            })
    driver.SetWindowSize(600, 400)
    driver.Load(self._http_server.GetUrl() + '/userAgent')
    self.assertTrue(driver.capabilities['mobileEmulationEnabled'])
    self.assertEqual(360, driver.ExecuteScript('return window.screen.width'))
    self.assertEqual(640, driver.ExecuteScript('return window.screen.height'))

  def testDeviceMetricsWithDeviceWidth(self):
    driver = self.CreateDriver(
        mobile_emulation = {
            'deviceMetrics': {'width': 360, 'height': 640, 'pixelRatio': 3},
            'userAgent': 'Mozilla/5.0 (Linux; Android 4.2.1; en-us; Nexus 5 Bui'
                         'ld/JOP40D) AppleWebKit/535.19 (KHTML, like Gecko) Chr'
                         'ome/18.0.1025.166 Mobile Safari/535.19'
            })
    driver.Load(self._http_server.GetUrl() + '/userAgentUseDeviceWidth')
    self.assertTrue(driver.capabilities['mobileEmulationEnabled'])
    self.assertEqual(360, driver.ExecuteScript('return window.screen.width'))
    self.assertEqual(640, driver.ExecuteScript('return window.screen.height'))

  def testUserAgent(self):
    driver = self.CreateDriver(
        mobile_emulation = {'userAgent': 'Agent Smith'})
    driver.Load(self._http_server.GetUrl() + '/userAgent')
    body_tag = driver.FindElement('tag name', 'body')
    self.assertEqual("Agent Smith", body_tag.GetText())

  def testDeviceName(self):
    driver = self.CreateDriver(
        mobile_emulation = {'deviceName': 'Google Nexus 5'})
    driver.Load(self._http_server.GetUrl() + '/userAgentUseDeviceWidth')
    self.assertEqual(360, driver.ExecuteScript('return window.screen.width'))
    self.assertEqual(640, driver.ExecuteScript('return window.screen.height'))
    body_tag = driver.FindElement('tag name', 'body')
    self.assertEqual(
        'Mozilla/5.0 (Linux; Android 4.4.4; en-us; Nexus 5 Build/JOP40D) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Xwalk/42.0.2307.2 Mobile '
        'Safari/537.36',
        body_tag.GetText())

  def testSendKeysToElement(self):
    driver = self.CreateDriver(
        mobile_emulation = {'deviceName': 'Google Nexus 5'})
    text = driver.ExecuteScript(
        'document.body.innerHTML = \'<input type="text">\';'
        'var input = document.getElementsByTagName("input")[0];'
        'input.addEventListener("change", function() {'
        '  document.body.appendChild(document.createElement("br"));'
        '});'
        'return input;')
    text.SendKeys('0123456789+-*/ Hi')
    text.SendKeys(', there!')
    value = driver.ExecuteScript('return arguments[0].value;', text)
    self.assertEquals('0123456789+-*/ Hi, there!', value)

  def testClickElement(self):
    driver = self.CreateDriver(
        mobile_emulation = {'deviceName': 'Google Nexus 5'})
    driver.Load('about:blank')
    div = driver.ExecuteScript(
        'document.body.innerHTML = "<div>old</div>";'
        'var div = document.getElementsByTagName("div")[0];'
        'div.addEventListener("click", function() {'
        '  div.innerHTML="new<br>";'
        '});'
        'return div;')
    div.Click()
    self.assertEquals(1, len(driver.FindElements('tag name', 'br')))

  def testHasTouchScreen(self):
    driver = self.CreateDriver(
        mobile_emulation = {'deviceName': 'Google Nexus 5'})
    self.assertIn('hasTouchScreen', driver.capabilities)
    self.assertTrue(driver.capabilities['hasTouchScreen'])


class XwalkDriverLogTest(unittest.TestCase):
  """Tests that xwalkdriver produces the expected log file."""

  UNEXPECTED_CHROMEOPTION_CAP = 'unexpected_xwalkoption_capability'
  LOG_MESSAGE = 'unrecognized xwalk option: %s' % UNEXPECTED_CHROMEOPTION_CAP

  def testXwalkDriverLog(self):
    _, tmp_log_path = tempfile.mkstemp(prefix='xwalkdriver_log_')
    xwalkdriver_server = server.Server(
        _CHROMEDRIVER_BINARY, log_path=tmp_log_path)
    try:
      driver = xwalkdriver.XwalkDriver(
          xwalkdriver_server.GetUrl(), xwalk_binary=_CHROME_BINARY,
          experimental_options={ self.UNEXPECTED_CHROMEOPTION_CAP : 1 })
      driver.Quit()
    except xwalkdriver.XwalkDriverException, e:
      self.assertTrue(self.LOG_MESSAGE in e.message)
    finally:
      xwalkdriver_server.Kill()
    with open(tmp_log_path, 'r') as f:
      self.assertTrue(self.LOG_MESSAGE in f.read())


class PerformanceLoggerTest(XwalkDriverBaseTest):
  """Tests xwalkdriver tracing support and Inspector event collection."""

  def testPerformanceLogger(self):
    driver = self.CreateDriver(
        experimental_options={'perfLoggingPrefs': {
            'traceCategories': 'webkit.console,blink.console'
          }}, performance_log_level='ALL')
    driver.Load(
        XwalkDriverTest._http_server.GetUrl() + '/xwalkdriver/empty.html')
    # Mark the timeline; later we will verify the marks appear in the trace.
    driver.ExecuteScript('console.time("foobar")')
    driver.ExecuteScript('console.timeEnd("foobar")')
    logs = driver.GetLog('performance')
    driver.Quit()

    marked_timeline_events = []
    seen_log_domains = {}
    for entry in logs:
      devtools_message = json.loads(entry['message'])['message']
      method = devtools_message['method']
      domain = method[:method.find('.')]
      seen_log_domains[domain] = True
      if method != 'Tracing.dataCollected':
        continue
      self.assertTrue('params' in devtools_message)
      self.assertTrue(isinstance(devtools_message['params'], dict))
      cat = devtools_message['params'].get('cat', '')
      # Depending on Xwalk version, the events may occur for the webkit.console
      # or blink.console category. They will only occur for one of them.
      if (cat == 'blink.console' or cat == 'webkit.console'):
        self.assertTrue(devtools_message['params']['name'] == 'foobar')
        marked_timeline_events.append(devtools_message)
    self.assertEquals(2, len(marked_timeline_events))
    self.assertEquals({'Network', 'Page', 'Tracing'},
                      set(seen_log_domains.keys()))


class SessionHandlingTest(XwalkDriverBaseTest):
  """Tests for session operations."""
  def testQuitASessionMoreThanOnce(self):
    driver = self.CreateDriver()
    driver.Quit()
    driver.Quit()

  def testGetSessions(self):
    driver = self.CreateDriver()
    response = driver.GetSessions()
    self.assertEqual(1, len(response))

    driver2 = self.CreateDriver()
    response = driver2.GetSessions()
    self.assertEqual(2, len(response))

class RemoteBrowserTest(XwalkDriverBaseTest):
  """Tests for XwalkDriver remote browser capability."""
  def setUp(self):
    self.assertTrue(_CHROME_BINARY is not None,
                    'must supply a xwalk binary arg')

  def testConnectToRemoteBrowser(self):
    port = self.FindFreePort()
    temp_dir = util.MakeTempDir()
    process = subprocess.Popen([_CHROME_BINARY,
                                '--remote-debugging-port=%d' % port,
                                '--user-data-dir=%s' % temp_dir,
                                '--use-mock-keychain'])
    if process is None:
      raise RuntimeError('Xwalk could not be started with debugging port')
    try:
      driver = self.CreateDriver(debugger_address='127.0.0.1:%d' % port)
      driver.ExecuteScript('console.info("%s")' % 'connecting at %d!' % port)
      driver.Quit()
    finally:
      process.terminate()

  def FindFreePort(self):
    for port in range(10000, 10100):
      try:
        socket.create_connection(('127.0.0.1', port), 0.2).close()
      except socket.error:
        return port
    raise RuntimeError('Cannot find open port')

class PerfTest(XwalkDriverBaseTest):
  """Tests for XwalkDriver perf."""
  def setUp(self):
    self.assertTrue(_REFERENCE_CHROMEDRIVER is not None,
                    'must supply a reference-xwalkdriver arg')

  def _RunDriverPerfTest(self, name, test_func):
    """Runs a perf test comparing a reference and new XwalkDriver server.

    Args:
      name: The name of the perf test.
      test_func: Called with the server url to perform the test action. Must
                 return the time elapsed.
    """
    class Results(object):
      ref = []
      new = []

    ref_server = server.Server(_REFERENCE_CHROMEDRIVER)
    results = Results()
    result_url_pairs = zip([results.new, results.ref],
                           [_CHROMEDRIVER_SERVER_URL, ref_server.GetUrl()])
    for iteration in range(30):
      for result, url in result_url_pairs:
        result += [test_func(url)]
      # Reverse the order for the next run.
      result_url_pairs = result_url_pairs[::-1]

    def PrintResult(build, result):
      mean = sum(result) / len(result)
      avg_dev = sum([abs(sample - mean) for sample in result]) / len(result)
      print 'perf result', build, name, mean, avg_dev, result
      util.AddBuildStepText('%s %s: %.3f+-%.3f' % (
          build, name, mean, avg_dev))

    # Discard first result, which may be off due to cold start.
    PrintResult('new', results.new[1:])
    PrintResult('ref', results.ref[1:])

  def testSessionStartTime(self):
    def Run(url):
      start = time.time()
      driver = self.CreateDriver(url)
      end = time.time()
      driver.Quit()
      return end - start
    self._RunDriverPerfTest('session start', Run)

  def testSessionStopTime(self):
    def Run(url):
      driver = self.CreateDriver(url)
      start = time.time()
      driver.Quit()
      end = time.time()
      return end - start
    self._RunDriverPerfTest('session stop', Run)

  def testColdExecuteScript(self):
    def Run(url):
      driver = self.CreateDriver(url)
      start = time.time()
      driver.ExecuteScript('return 1')
      end = time.time()
      driver.Quit()
      return end - start
    self._RunDriverPerfTest('cold exe js', Run)

if __name__ == '__main__':
  parser = optparse.OptionParser()
  parser.add_option(
      '', '--xwalkdriver',
      help='Path to xwalkdriver server (REQUIRED!)')
  parser.add_option(
      '', '--log-path',
      help='Output verbose server logs to this file')
  parser.add_option(
      '', '--reference-xwalkdriver',
      help='Path to the reference xwalkdriver server')
  parser.add_option(
      '', '--xwalk', help='Path to a build of the xwalk binary')
  parser.add_option(
      '', '--xwalk-version', default='HEAD',
      help='Version of xwalk. Default is \'HEAD\'.')
  parser.add_option(
      '', '--filter', type='string', default='*',
      help=('Filter for specifying what tests to run, "*" will run all. E.g., '
            '*testStartStop'))
  parser.add_option(
      '', '--android-package',
      help=('Android package key. Possible values: ' +
            str(_ANDROID_NEGATIVE_FILTER.keys())))
  options, args = parser.parse_args()

  options.xwalkdriver = util.GetAbsolutePathOfUserPath(options.xwalkdriver)
  if not options.xwalkdriver or not os.path.exists(options.xwalkdriver):
    parser.error('xwalkdriver is required or the given path is invalid.' +
                 'Please run "%s --help" for help' % __file__)

  global _CHROMEDRIVER_BINARY
  _CHROMEDRIVER_BINARY = options.xwalkdriver

  if (options.android_package and
      options.android_package not in _ANDROID_NEGATIVE_FILTER):
    parser.error('Invalid --android-package')

  xwalkdriver_server = server.Server(_CHROMEDRIVER_BINARY, options.log_path)
  global _CHROMEDRIVER_SERVER_URL
  _CHROMEDRIVER_SERVER_URL = xwalkdriver_server.GetUrl()

  global _REFERENCE_CHROMEDRIVER
  _REFERENCE_CHROMEDRIVER = util.GetAbsolutePathOfUserPath(
      options.reference_xwalkdriver)

  global _CHROME_BINARY
  if options.xwalk:
    _CHROME_BINARY = util.GetAbsolutePathOfUserPath(options.xwalk)
  else:
    _CHROME_BINARY = None

  global _ANDROID_PACKAGE_KEY
  _ANDROID_PACKAGE_KEY = options.android_package

  if options.filter == '*':
    if _ANDROID_PACKAGE_KEY:
      negative_filter = _ANDROID_NEGATIVE_FILTER[_ANDROID_PACKAGE_KEY]
    else:
      negative_filter = _GetDesktopNegativeFilter(options.xwalk_version)
    options.filter = '*-' + ':__main__.'.join([''] + negative_filter)

  all_tests_suite = unittest.defaultTestLoader.loadTestsFromModule(
      sys.modules[__name__])
  tests = unittest_util.FilterTestSuite(all_tests_suite, options.filter)
  XwalkDriverTest.GlobalSetUp()
  MobileEmulationCapabilityTest.GlobalSetUp()
  result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(tests)
  XwalkDriverTest.GlobalTearDown()
  MobileEmulationCapabilityTest.GlobalTearDown()
  sys.exit(len(result.failures) + len(result.errors))
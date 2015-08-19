// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/logging.h"
#include "base/strings/string16.h"
#include "base/strings/stringprintf.h"
#include "base/strings/utf_string_conversions.h"
#include "xwalk/test/xwalkdriver/xwalk/ui_events.h"
#include "xwalk/test/xwalkdriver/keycode_text_conversion.h"
#include "ui/events/event_constants.h"
#include "ui/events/keycodes/dom/dom_code.h"
#include "ui/events/keycodes/keyboard_code_conversion.h"
#include "ui/events/ozone/layout/keyboard_layout_engine.h"
#include "ui/events/ozone/layout/keyboard_layout_engine_manager.h"

bool ConvertKeyCodeToText(ui::KeyboardCode key_code,
                          int modifiers,
                          std::string* text,
                          std::string* error_msg) {
  ui::KeyboardLayoutEngine* keyboard_layout_engine =
      ui::KeyboardLayoutEngineManager::GetKeyboardLayoutEngine();
  ui::DomCode dom_code = ui::UsLayoutKeyboardCodeToDomCode(key_code);
  int event_flags = ui::EF_NONE;

  // Xwalk OS keyboards don't have meta or num lock keys, so these modifier
  // masks are ignored. Only handle alt, ctrl and shift.
  if (modifiers & kAltKeyModifierMask)
    event_flags |= ui::EF_ALT_DOWN;
  if (modifiers & kControlKeyModifierMask)
    event_flags |= ui::EF_CONTROL_DOWN;
  if (modifiers & kShiftKeyModifierMask)
    event_flags |= ui::EF_SHIFT_DOWN;

  ui::DomKey dom_key_ignored;
  base::char16 str[2] = {'\0'};
  ui::KeyboardCode key_code_ignored;
  uint32 platform_keycode_ignored;

  if (!keyboard_layout_engine->Lookup(dom_code, event_flags, &dom_key_ignored,
                                      &str[0], &key_code_ignored,
                                      &platform_keycode_ignored)) {
    // Key codes like ui::VKEY_UNKNOWN need to be mapped to the empty string, so
    // even if the lookup fails we still need to return true here.
    *text = std::string();
    return true;
  }

  if (!base::UTF16ToUTF8(str, base::c16len(str), text)) {
    *error_msg = base::StringPrintf(
        "unicode conversion failed for keycode %d with modifiers 0x%x",
        key_code, modifiers);
    return false;
  }

  return true;
}

bool ConvertCharToKeyCode(base::char16 key,
                          ui::KeyboardCode* key_code,
                          int* necessary_modifiers,
                          std::string* error_msg) {
  base::string16 key_string;
  key_string.push_back(key);
  std::string key_string_utf8 = base::UTF16ToUTF8(key_string);
  bool found_code = false;
  *error_msg = std::string();
  // There doesn't seem to be a way to get a CrOS key code for a given unicode
  // character. So here we check every key code to see if it produces the
  // right character, as we do on Mac (see keycode_text_conversion_mac.mm).
  for (int i = 0; i < 256; ++i) {
    ui::KeyboardCode code = static_cast<ui::KeyboardCode>(i);
    // Skip the numpad keys.
    if (code >= ui::VKEY_NUMPAD0 && code <= ui::VKEY_DIVIDE)
      continue;
    std::string key_string;
    if (!ConvertKeyCodeToText(code, 0, &key_string, error_msg))
      return false;
    found_code = key_string_utf8 == key_string;
    std::string key_string_utf8_tmp;
    if (!ConvertKeyCodeToText(code, kShiftKeyModifierMask, &key_string_utf8_tmp,
                              error_msg))
      return false;
    if (!found_code && key_string_utf8 == key_string_utf8_tmp) {
      *necessary_modifiers = kShiftKeyModifierMask;
      found_code = true;
    }
    if (found_code) {
      *key_code = code;
      break;
    }
  }
  return found_code;
}
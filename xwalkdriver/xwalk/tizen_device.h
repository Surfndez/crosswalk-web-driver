// Copyright (c) 2013 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef XWALK_TEST_XWALKDRIVER_XWALK_TIZEN_DEVICE_H_
#define XWALK_TEST_XWALKDRIVER_XWALK_TIZEN_DEVICE_H_

#include <list>
#include <string>

#include "base/callback.h"
#include "base/compiler_specific.h"
#include "base/memory/ref_counted.h"
#include "base/memory/scoped_ptr.h"
#include "base/synchronization/lock.h"
#include "xwalk/test/xwalkdriver/xwalk/device.h"

class DeviceBridge;
class Status;
class DeviceManager;

class TizenDevice : public Device{
 public:
  virtual ~TizenDevice();

  virtual Status SetUp(const std::string& app_id,
                       const std::string& args,
                       int local_port,
                       int remote_port) override;

  virtual Status TearDown() override;

 private:
  friend class DeviceManager;

  TizenDevice(const std::string& device_serial,
              DeviceBridge* device_bridge,
              base::Callback<void()> release_callback);

  const std::string serial_;
  std::string active_app_;
  DeviceBridge* device_bridge_;
  base::Callback<void()> release_callback_;

  DISALLOW_COPY_AND_ASSIGN(TizenDevice);
};

#endif  // XWALK_TEST_XWALKDRIVER_XWALK_TIZEN_DEVICE_H_

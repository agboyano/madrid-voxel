// The browser the measurement tools use: the system Chromium ($CHROMIUM, else /usr/bin/chromium) rendering through
// ANGLE's Vulkan backend on the real GPU, as scripts/screenshot.py does; swift = SwiftShader on the CPU.
import { chromium } from 'playwright-core';

export const launch = ({ swift = false } = {}) => chromium.launch({
  headless: true,
  executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
  args: swift ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : ['--use-angle=vulkan', '--enable-features=Vulkan', '--ignore-gpu-blocklist'],
});

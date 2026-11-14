// The browser the measurement tools use: the system Chromium ($CHROMIUM, else /usr/bin/chromium) rendering through
// ANGLE's Vulkan backend on the real GPU, as scripts/screenshot.py does; swift = SwiftShader on the CPU.
import { chromium } from 'playwright-core';

// args: extra switches, e.g. --enable-precise-memory-info for the tools that read performance.memory
export const launch = ({ swift = false, args = [] } = {}) => chromium.launch({
  headless: true,
  executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
  args: [...(swift ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : ['--use-angle=vulkan', '--enable-features=Vulkan', '--ignore-gpu-blocklist']), ...args],
});

// The same random numbers on every run (the street life draws on Math.random): two runs of one build then give the
// same traffic, so a change in the traffic statistics comes from the code, not from chance
export const seedRandom = (page, seed = 1234567) => page.addInitScript((seed) => {
  let s = seed; Math.random = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
}, seed);

import baseConfig from '../../../frontend/playwright.config'

const frontendRoot = process.cwd()

export default {
  ...baseConfig,
  testDir: `${frontendRoot}/e2e`,
  outputDir: `${frontendRoot}/test-results`,
  reporter: [
    ['list'],
    [
      'json',
      {
        outputFile:
          process.env.PLAYWRIGHT_JSON_OUTPUT_NAME ??
          `${frontendRoot}/test-results/delivery-playwright-results.json`,
      },
    ],
  ],
  projects: baseConfig.projects?.map((project) => ({
    ...project,
    use: {
      ...project.use,
      // Playwright's "chromium" channel uses the installed full Chromium
      // binary and does not require the optional chromium-headless-shell.
      channel: 'chromium',
    },
  })),
  webServer:
    baseConfig.webServer && !Array.isArray(baseConfig.webServer)
      ? { ...baseConfig.webServer, cwd: frontendRoot }
      : baseConfig.webServer,
}

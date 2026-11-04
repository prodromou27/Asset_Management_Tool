import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

// The suite runs files in parallel; under load the first render of the full app shell can
// take longer than Testing Library's 1 s default for findBy*/waitFor.
configure({ asyncUtilTimeout: 5000 })

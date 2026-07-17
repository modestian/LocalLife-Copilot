import 'vue-router'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    guestOnly?: boolean
    publicReadOnly?: boolean
    redirectAuthenticated?: boolean
    title?: string
    roles?: string[]
  }
}

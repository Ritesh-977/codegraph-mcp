package com.foo.app

import com.foo.service.UserService

class App(private val svc: UserService = UserService()) {
    fun run(id: String): String = svc.find(id)
}

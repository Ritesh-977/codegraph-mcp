package com.foo.service

import com.foo.repo.UserRepo

class UserService(private val repo: UserRepo = UserRepo()) {
    fun find(id: String): String = repo.findById(id)
}

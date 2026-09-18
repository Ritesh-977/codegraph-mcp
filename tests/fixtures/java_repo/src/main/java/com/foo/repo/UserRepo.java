package com.foo.repo;

public class UserRepo {
    public String findById(String id) {
        return "user:" + id;
    }
}

package com.foo.service;

import com.foo.repo.UserRepo;

public class UserService {
    private UserRepo repo = new UserRepo();

    public String find(String id) {
        return repo.findById(id);
    }
}

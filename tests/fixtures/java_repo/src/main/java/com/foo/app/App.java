package com.foo.app;

import com.foo.service.UserService;

public class App {
    private UserService svc = new UserService();

    public String run(String id) {
        return svc.find(id);
    }
}

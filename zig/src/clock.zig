const std = @import("std");
const errors = @import("errors.zig");

const Buttons = @import("buttons.zig").Buttons;

pub const Clock = struct {
    profile: u32,
    turbo: bool,
    buttons: *Buttons,

    cycle: u32,
    frame: u32,
    timer: std.time.Timer,
    start: std.time.Timer,

    pub fn new(buttons: *Buttons, profile: u32, turbo: bool) !Clock {
        return Clock{
            .profile = profile,
            .turbo = turbo,
            .buttons = buttons,
            .timer = try std.time.Timer.start(),
            .start = try std.time.Timer.start(),
            .cycle = 0,
            .frame = 0,
        };
    }

    pub fn tick(self: *Clock) !void {
        self.cycle += 1;

        // Do a whole frame's worth of sleeping at the start of each frame
        if (self.cycle % 17556 == 20) {
            // Sleep if we have time left over
            var time_spent = self.timer.lap();
            const time_per_frame = 1_000_000_000 / 60;
            if (!self.turbo and !self.buttons.turbo and time_spent < time_per_frame) {
                var sleep_time = time_per_frame - time_spent;
                std.time.sleep(sleep_time);
            }

            // Exit if we've hit the frame limit
            if ((self.profile != 0) and (self.frame >= self.profile)) {
                var duration: f64 = @intToFloat(f64, self.start.read());
                std.debug.print("Emulated {d} frames in {d:5.2}s ({d:.0}fps)\n", .{
                    self.frame,
                    duration / 1_000_000_000.0,
                    @intToFloat(f64, self.frame) / (duration / 1_000_000_000.0),
                });
                return errors.ControlledExit.Timeout;
            }

            self.frame += 1;
        }
    }
};

use structopt::StructOpt;
extern crate sdl2;

mod buttons;
mod cart;
mod clock;
mod consts;
mod cpu;
mod gpu;
mod ram;
mod apu;

#[derive(StructOpt)]
#[structopt(about = "Shish's Gameboy Emulator: Rust Edition")]
struct Args {
    /// Disable GUI
    #[structopt(short="H")]
    headless: bool,

    /// Disable Sound
    #[structopt(short="S")]
    silent: bool,

    /// Debug CPU
    #[structopt(short = "c", long)]
    debug_cpu: bool,

    /// Debug GPU
    #[structopt(short = "g", long)]
    debug_gpu: bool,

    /// Debug APU
    #[structopt(short="a", long)]
    debug_apu: bool,

    /// Debug Memory
    #[structopt(short = "m", long)]
    debug_ram: bool,

    /// Profile for 10s then exit
    #[structopt(short, long)]
    profile: bool,

    /// No sleep()
    #[structopt(short, long)]
    turbo: bool,

    /// Path to a .gb file
    #[structopt(short, default_value = "game.gb")]
    romfile: String,
}

struct Gameboy {
    sdl: sdl2::Sdl,
    //cart: cart::Cart,
    ram: ram::RAM,
    cpu: cpu::CPU,
    gpu: gpu::GPU,
    apu: apu::APU,
    buttons: buttons::Buttons,
    clock: clock::Clock,
}
impl Gameboy {
    #[inline(never)]
    fn init(args: Args) -> Result<Gameboy, String> {
        let sdl = sdl2::init()?;

        let cart = cart::Cart::init(args.romfile.as_str()).unwrap();
        let ram = ram::RAM::init(cart, args.debug_ram);
        let cpu = cpu::CPU::init(args.debug_cpu);
        let gpu = gpu::GPU::init(&sdl, args.romfile.as_str(), args.headless, args.debug_gpu)?;
        let apu = apu::APU::init(args.silent, args.debug_apu);
        let buttons = buttons::Buttons::init()?;
        let clock = clock::Clock::init(args.profile, args.turbo);

        Ok(Gameboy {
            sdl,
            //cart,
            ram,
            cpu,
            gpu,
            apu,
            buttons,
            clock,
        })
    }

    #[inline(never)]
    fn run(&mut self) {
        self.apu.tick();

        loop {
            if !self.cpu.tick(&mut self.ram) {
                println!("Break from CPU");
                break;
            }
            if !self.buttons.tick(&self.sdl, &mut self.ram, &mut self.cpu) {
                println!("Break from buttons");
                break;
            }
            self.gpu.tick(&mut self.ram, &mut self.cpu);
            if !self.clock.tick() {
                println!("Break from clock");
                break;
            }
        }
    }
}

fn main() -> Result<(), String> {
    Gameboy::init(Args::from_args())?.run();

    // because debug ROMs print to stdout without newline
    println!();

    Ok(())
}

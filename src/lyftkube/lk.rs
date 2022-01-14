use std::process::Command;

pub fn lk(commands: &Vec<String>) {
    let (mut cluster, mut pod) = ("", "");
    let cmds: Vec<String> = commands.iter().map(|c| {
        if c.contains("/") {
            let split: Vec<&str> = c.split("/").collect();
            if split.iter().count() == 2 {
                cluster = split[0];
                pod = split[1];

                return pod.to_string();
            }
        }
        return c.to_string();
    }).collect();

    let env = if cluster.contains("staging") { "staging" } else { "production" };
    let proj = pod.split("-").next().unwrap();

    let final_cmd = format!(
        "--cluster {} -e {} kubectl -- -n {}-{} {}",
        cluster, env, proj, env, cmds.join(" ")
    );

    println!("lyftkube {}", final_cmd);
    let mut child = Command::new("lyftkube").args(final_cmd.split(" "))
                                            .spawn()
                                            .unwrap();
    child.wait().unwrap();
}

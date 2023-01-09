use std::process::Command;

fn lk_to_kubectl(commands: &Vec<String>) -> String {
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

    return format!(
        "--cluster {} -e {} kubectl -- -n {}-{} {}",
        cluster, env, proj, env, cmds.join(" ")
    );
}

pub fn lk(commands: &Vec<String>) {
    let final_cmd = lk_to_kubectl(commands);
    println!("lyftkube {}", final_cmd);
    let mut child = Command::new("lyftkube").args(final_cmd.split(" "))
                                            .spawn()
                                            .unwrap();
    child.wait().unwrap();
}

#[cfg(test)]
mod tests {
    use crate::lyftkube::lk::lk_to_kubectl;

    #[test]
    fn test_lk_works() {
        let expected = "--cluster some-staging-1 -e staging kubectl -- -n abc-staging get pod abc-def-xxx-yyy";
        let cmds: Vec<String> = ["get", "pod", "some-staging-1/abc-def-xxx-yyy"].iter().map(|d| d.to_string()).collect();
        let real = lk_to_kubectl(&cmds);
        assert_eq!(expected, real);
    }

    #[test]
    fn test_lk_not_work_when_no_cluster_pod() {
        let expected = "--cluster some-staging-1 -e staging kubectl -- -n abc-staging get pod abc-def-xxx-yyy";
        let cmds: Vec<String> = ["get", "pod", "abc-def-xxx-yyy"].iter().map(|d| d.to_string()).collect();
        let real = lk_to_kubectl(&cmds);
        assert_ne!(expected, real);
    }
}

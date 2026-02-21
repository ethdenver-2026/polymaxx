resource "aws_route53_zone" "polymaxx_health" {
  name = "polymaxx.health"

  tags = {
    Name    = "${local.name_prefix}-route53-zone"
    Project = var.project_name
  }
}

resource "aws_route53_record" "consumer_a" {
  zone_id = aws_route53_zone.polymaxx_health.zone_id
  name    = "a.polymaxx.health"
  type    = "A"

  alias {
    name                   = aws_lb.consumer.dns_name
    zone_id                = aws_lb.consumer.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "root" {
  zone_id = aws_route53_zone.polymaxx_health.zone_id
  name    = "polymaxx.health"
  type    = "A"

  alias {
    name                   = aws_lb.consumer.dns_name
    zone_id                = aws_lb.consumer.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "consumer_b" {
  zone_id = aws_route53_zone.polymaxx_health.zone_id
  name    = "b.polymaxx.health"
  type    = "A"

  alias {
    name                   = aws_lb.consumer.dns_name
    zone_id                = aws_lb.consumer.zone_id
    evaluate_target_health = true
  }
}

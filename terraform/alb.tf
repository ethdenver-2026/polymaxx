resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "HTTP/HTTPS ingress for ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.name_prefix}-alb-sg"
    Project = var.project_name
  }
}

resource "aws_lb" "consumer" {
  name               = "signal-market-consumer-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public.id, aws_subnet.public_b.id]

  tags = {
    Name    = "${local.name_prefix}-consumer-alb"
    Project = var.project_name
  }
}

resource "aws_lb_target_group" "consumer_a_ui" {
  name        = "signal-mkt-a-ui-tg"
  port        = 5173
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group" "consumer_b_ui" {
  name        = "signal-mkt-b-ui-tg"
  port        = 5174
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group_attachment" "consumer_a_ui_instance" {
  target_group_arn = aws_lb_target_group.consumer_a_ui.arn
  target_id        = aws_instance.docker_host.id
  port             = 5173
}

resource "aws_lb_target_group_attachment" "consumer_b_ui_instance" {
  target_group_arn = aws_lb_target_group.consumer_b_ui.arn
  target_id        = aws_instance.docker_host.id
  port             = 5174
}

resource "aws_acm_certificate" "polymaxx_health" {
  domain_name               = "a.polymaxx.health"
  validation_method         = "DNS"
  subject_alternative_names = ["b.polymaxx.health"]

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name    = "${local.name_prefix}-polymaxx-cert"
    Project = var.project_name
  }
}

resource "aws_route53_record" "acm_validation" {
  for_each = {
    for dvo in aws_acm_certificate.polymaxx_health.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = aws_route53_zone.polymaxx_health.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "polymaxx_health" {
  certificate_arn         = aws_acm_certificate.polymaxx_health.arn
  validation_record_fqdns = [for record in aws_route53_record.acm_validation : record.fqdn]
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.consumer.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.consumer.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.polymaxx_health.certificate_arn

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Not found"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener_rule" "consumer_a_host" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.consumer_a_ui.arn
  }

  condition {
    host_header {
      values = ["a.polymaxx.health", "polymaxx.health"]
    }
  }
}

resource "aws_lb_listener_rule" "consumer_b_host" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.consumer_b_ui.arn
  }

  condition {
    host_header {
      values = ["b.polymaxx.health"]
    }
  }
}
